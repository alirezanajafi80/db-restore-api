from pydantic import BaseModel, Field


class RestoreResultSchema(BaseModel):
    table: str = Field(description="Table name")
    missing_ids: list[int] = Field(default_factory=list, description="IDs present in backup but missing in main")
    restored_ids: list[int] = Field(default_factory=list, description="IDs successfully restored")
    failed_ids: list[int] = Field(default_factory=list, description="IDs that failed to restore")
    errors: dict[str, str] = Field(default_factory=dict,
                                   description="Error messages keyed by ID or '-1' for table-level errors")

    @property
    def full_table_name(self) -> str:
        """Return fully qualified table name with schema"""
        return f"{self.schema}.{self.table}" if self.schema else self.table

    def model_dump(self, **kwargs) -> dict:
        """Override dump to include computed property if needed"""
        data = super().model_dump(**kwargs)
        data['full_table_name'] = self.full_table_name
        return data