"""
asyncpg utility functions
Provides common database-operation helpers
"""
import logging
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
import json
import uuid as uuid_module

logger = logging.getLogger(__name__)


def generate_uuid() -> str:
    """Generate a UUID."""
    return str(uuid_module.uuid4())


def now_utc() -> datetime:
    """Get the current UTC time."""
    return datetime.utcnow()


def utc_isoformat(dt: Optional[datetime]) -> Optional[str]:
    """
    Serialize a datetime "assumed to be UTC" into an ISO 8601 string with a trailing Z, for API responses.
    The backend stores UTC uniformly and returns it with Z; the frontend's new Date(s) parses it as UTC and displays it in local time.
    - naive datetime: treated as UTC, append Z
    - timezone-aware: format as ...Z if UTC, otherwise keep the offset
    """
    if dt is None:
        return None
    if not hasattr(dt, "isoformat"):
        return str(dt)
    s = dt.isoformat()
    if getattr(dt, "tzinfo", None) is None:
        return s + "Z"
    if s.endswith("+00:00"):
        return s[:-6] + "Z"
    return s


def to_json(data: Any) -> Optional[str]:
    """Convert to a JSON string."""
    if data is None:
        return None
    return json.dumps(data)


def from_json(data: Optional[str]) -> Any:
    """Parse from a JSON string."""
    if data is None:
        return None
    return json.loads(data)


def ensure_list(value: Any) -> Optional[List]:
    """Normalize a JSON string or scalar the DB may return into a List (for msgspec Struct List fields).

    Key fixes:
    1. Handle the JSON string 'null' (json.loads returns None)
    2. Filter None values out of the list (to avoid [None] becoming ['null'])
    """
    if value is None:
        return None
    if isinstance(value, list):
        # filter None values out of the list
        return [v for v in value if v is not None]
    if isinstance(value, str):
        # handle the JSON string 'null'
        if value == 'null':
            return None
        try:
            parsed = json.loads(value)
            # json.loads('null') returns None
            if parsed is None:
                return None
            # if it is a list, filter out None values
            if isinstance(parsed, list):
                return [v for v in parsed if v is not None]
            # wrap other types into a list
            return [parsed]
        except (json.JSONDecodeError, TypeError):
            return [value]
    return list(value) if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)) else [value]


def ensure_dict(value: Any) -> Optional[Dict[str, Any]]:
    """Normalize a JSON string the DB may return into a Dict (for msgspec Struct Dict fields)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


# ==================== Generic: DB row <-> msgspec Struct compatibility (when dev/prod table schemas differ) ====================
# Usage: any CRUD uses row_to_struct(row, XxxDB) when "building a Struct from a DB row"; uses build_insert_row(XxxDB, **kwargs) "before INSERT".
# This way extra DB columns or missing schema columns do not raise Unexpected keyword argument; columns in the schema but not yet in the DB are not written.

def struct_allowed_keys(struct_cls: type) -> set:
    """Return the set of field names currently defined on struct_cls (msgspec.Struct)."""
    return set(getattr(struct_cls, "__struct_fields__", ()))


def filter_row_to_struct_keys(row: Optional[Dict], struct_cls: type) -> Optional[Dict]:
    """Keep only keys that exist in struct_cls. Avoids Unexpected keyword argument when the DB has extra columns not yet added to the schema."""
    if row is None:
        return None
    allowed = struct_allowed_keys(struct_cls)
    return {k: v for k, v in row.items() if k in allowed}


def row_to_struct(row: Optional[Dict], struct_cls: type):
    """Build a Struct instance from a DB row, passing only keys that exist in the schema. Works with any table/Struct."""
    filtered = filter_row_to_struct_keys(row, struct_cls)
    return struct_cls(**filtered) if filtered else None


def build_insert_row(struct_cls: type, **kwargs) -> Dict:
    """Keep only keys that exist in struct_cls, for INSERT. Columns not in the current schema are not written, avoiding errors when the DB lacks the column."""
    allowed = struct_allowed_keys(struct_cls)
    return {k: v for k, v in kwargs.items() if k in allowed}


async def fetch_one(conn, query: str, *args) -> Optional[Dict]:
    """Execute a query and return a single row (as a dict)."""
    try:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"fetch_one 失败: {e}, query: {query[:100]}")
        raise


async def fetch_all(conn, query: str, *args) -> List[Dict]:
    """Execute a query and return all rows (as a list of dicts)."""
    try:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"fetch_all 失败: {e}, query: {query[:100]}")
        raise


async def fetch_val(conn, query: str, *args) -> Any:
    """Execute a query and return a single value."""
    try:
        return await conn.fetchval(query, *args)
    except Exception as e:
        logger.error(f"fetch_val 失败: {e}, query: {query[:100]}")
        raise


async def execute(conn, query: str, *args) -> str:
    """Execute a DML statement (INSERT/UPDATE/DELETE)."""
    try:
        return await conn.execute(query, *args)
    except Exception as e:
        logger.error(f"execute 失败: {e}, query: {query[:100]}")
        raise


async def insert_and_return(conn, query_or_table: str, *args, **kwargs) -> Optional[Dict]:
    """Execute an INSERT and return the inserted row.
    Two usages:
    1) insert_and_return(conn, "INSERT INTO t (...) VALUES (...) RETURNING *", *values)
    2) insert_and_return(conn, "table_name", col1=val1, col2=val2, ...) builds the SQL via build_insert_query
    """
    try:
        if kwargs:
            query, values = build_insert_query(query_or_table, kwargs)
            row = await conn.fetchrow(query, *values)
        else:
            row = await conn.fetchrow(query_or_table, *args)
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"insert_and_return 失败: {e}, query: {query_or_table[:100]}")
        raise


def build_where_clause(filters: Dict[str, Any], start_idx: int = 1) -> tuple[str, List[Any]]:
    """Build a WHERE clause.

    Args:
        filters: filter dict {column: value}
        start_idx: starting parameter index (default starts at $1)

    Returns:
        a (where_clause, values) tuple
    """
    if not filters:
        return "", []

    conditions = []
    values = []
    idx = start_idx

    for column, value in filters.items():
        if value is not None:
            conditions.append(f'"{column}" = ${idx}')
            values.append(value)
            idx += 1

    where_clause = " AND ".join(conditions) if conditions else ""
    return where_clause, values


def _clean_list_for_json(lst: list) -> list:
    """Clean None values out of a list, to prevent json.dumps from producing a 'null' string."""
    return [v for v in lst if v is not None]


def build_insert_query(table: str, data: Dict[str, Any]) -> tuple[str, List[Any]]:
    """Build an INSERT query.

    Args:
        table: table name
        data: data dict {column: value}

    Returns:
        a (query, values) tuple

    Key fixes:
    1. Filter None values out of lists, to prevent json.dumps([None]) from producing '[null]'
    2. Do not insert empty lists (avoids asyncpg type-inference errors)
    """
    import json

    filtered_data = {}
    for k, v in data.items():
        if v is None:
            continue

        # handle lists: clean None values
        if isinstance(v, list):
            cleaned = _clean_list_for_json(v)
            # skip empty lists: asyncpg cannot infer the element type of an empty list
            if len(cleaned) == 0:
                continue
            filtered_data[k] = json.dumps(cleaned)
        # handle dicts
        elif isinstance(v, dict):
            filtered_data[k] = json.dumps(v)
        else:
            filtered_data[k] = v

    columns = list(filtered_data.keys())
    values = list(filtered_data.values())
    placeholders = [f"${i+1}" for i in range(len(columns))]
    # wrap column names in double quotes, to avoid reserved keywords (e.g. order) causing a syntax error
    quoted_columns = ', '.join(f'"{c}"' for c in columns)
    query = f"""
        INSERT INTO {table} ({quoted_columns})
        VALUES ({', '.join(placeholders)})
        RETURNING *
    """
    return query, values


def build_update_query(
    table: str,
    data: Dict[str, Any],
    where: Dict[str, Any]
) -> tuple[str, List[Any]]:
    """Build an UPDATE query.

    Args:
        table: table name
        data: update-data dict {column: value}
        where: WHERE condition dict {column: value}

    Returns:
        a (query, values) tuple

    Key fixes:
    1. Filter None values out of lists, to prevent json.dumps([None]) from producing '[null]'
    2. Skip empty lists (avoids asyncpg type-inference errors)
    """
    import json

    filtered_data = {}
    for k, v in data.items():
        if v is None:
            continue

        # handle lists: clean None values
        if isinstance(v, list):
            cleaned = _clean_list_for_json(v)
            # skip empty lists: asyncpg cannot infer the element type of an empty list
            if len(cleaned) == 0:
                continue
            filtered_data[k] = json.dumps(cleaned)
        # handle dicts
        elif isinstance(v, dict):
            filtered_data[k] = json.dumps(v)
        else:
            filtered_data[k] = v

    set_parts = []
    values = []
    idx = 1

    # build the SET clause (double-quote column names to avoid reserved keywords like order)
    for column, value in filtered_data.items():
        set_parts.append(f'"{column}" = ${idx}')
        values.append(value)
        idx += 1

    # build the WHERE clause
    where_clause, where_values = build_where_clause(where, start_idx=idx)
    values.extend(where_values)

    query = f"""
        UPDATE {table}
        SET {', '.join(set_parts)}
        WHERE {where_clause}
        RETURNING *
    """

    return query, values
