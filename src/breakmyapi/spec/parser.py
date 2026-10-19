from dataclasses import dataclass

import yaml

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


class SpecError(ValueError):
    pass


@dataclass
class Endpoint:
    method: str
    path: str
    has_path_id: bool
    requires_auth: bool
    accepts_body: bool
    is_admin: bool


def load_spec(text: str) -> dict:
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SpecError(f"Spec is not valid YAML or JSON: {e}") from e
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise SpecError("Spec has no 'paths' section")
    return spec


def parse_endpoints(spec: dict) -> list[Endpoint]:
    global_security = spec.get("security", [])
    endpoints = []
    for path, path_item in spec["paths"].items():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            security = operation.get("security", global_security)
            endpoints.append(Endpoint(
                method=method.upper(),
                path=path,
                has_path_id="{" in path,
                requires_auth=any(security),
                accepts_body="requestBody" in operation,
                is_admin="admin" in operation.get("tags", []) or "/admin" in path,
            ))
    return endpoints
