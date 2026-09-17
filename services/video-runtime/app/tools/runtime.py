"""Small async-tool primitives used by the video provider adapters.

The video runtime invokes provider tools directly.  It only needs stable tool
metadata, an async callable, and a context carrier; importing an agent framework
for those three properties would couple every leaf provider to another loop.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import update_wrapper
from typing import Any, Callable, Generic, TypeVar


ContextT = TypeVar("ContextT")


@dataclass
class ToolRuntime(Generic[ContextT]):
    """Runtime values passed explicitly by the atomic provider boundary."""

    context: ContextT
    config: Any = None


class AsyncTool:
    """Callable metadata wrapper for one asynchronous provider function."""

    def __init__(
        self,
        function: Callable[..., Any],
        *,
        name: str,
        args_schema: type[Any] | None = None,
        response_format: str = "content",
    ) -> None:
        self.coroutine = function
        self.name = name
        self.description = inspect.getdoc(function) or ""
        self.args_schema = args_schema
        self.response_format = response_format
        self.metadata: dict[str, Any] | None = None
        update_wrapper(self, function)

    async def ainvoke(
        self,
        arguments: dict[str, Any] | Any,
        config: Any = None,
    ) -> Any:
        """Invoke the provider with explicit keyword arguments."""
        del config
        values = arguments if isinstance(arguments, dict) else vars(arguments)
        return await self.coroutine(**values)


BaseTool = AsyncTool


def tool(
    name: Any = None,
    *,
    args_schema: type[Any] | None = None,
    response_format: str = "content",
) -> Callable[[Callable[..., Any]], AsyncTool] | AsyncTool:
    """Decorate an async provider function with the metadata its callers use."""

    if callable(name) and not isinstance(name, (str, bytes)):
        function = name
        return AsyncTool(
            function,
            name=function.__name__,
            args_schema=args_schema,
            response_format=response_format,
        )

    def decorate(function: Callable[..., Any]) -> AsyncTool:
        resolved = getattr(name, "value", name) or function.__name__
        return AsyncTool(
            function,
            name=str(resolved),
            args_schema=args_schema,
            response_format=response_format,
        )

    return decorate
