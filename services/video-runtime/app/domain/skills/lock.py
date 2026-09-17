from pydantic import BaseModel


class SkillLock(BaseModel):
    project_id: str
    skill_id: str
    version: str
    digest: str
    source: str
    enabled: bool = True
