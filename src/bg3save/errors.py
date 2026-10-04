from __future__ import annotations


class SaveError(Exception):
    def __init__(self, code: str, message: str, *, status: str = "UNSUPPORTED", details=None):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details

    def as_json(self) -> dict:
        result = {"schema_version": 1, "status": self.status,
                  "error": {"code": self.code, "message": str(self)}}
        if self.details is not None:
            result["error"]["details"] = self.details
        return result
