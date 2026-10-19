"""The fixed list of check types. Nothing outside this list is ever tested or reported."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    id: str
    name: str
    catches: str


CHECKS: dict[str, Check] = {
    c.id: c
    for c in [
        Check("object_level_access", "Object-level access",
              "User B reads or edits user A's record by changing an ID"),
        Check("missing_auth", "Missing auth",
              "An endpoint works without a valid login token"),
        Check("mass_assignment", "Mass assignment",
              "A user sets a field they should not, such as role=admin"),
        Check("excessive_data", "Excessive data",
              "A response returns password hashes or fields outside the spec's schema"),
        Check("bad_input_handling", "Bad input handling",
              "Wrong types or missing fields cause a 500 instead of a clean 400"),
        Check("leaky_errors", "Leaky errors",
              "Stack traces or database errors shown to the caller"),
        Check("spec_mismatch", "Spec mismatch",
              "Fields or status codes differ from what the spec promises"),
        Check("admin_route_exposure", "Admin route exposure",
              "A normal user can call an admin-only endpoint"),
        Check("no_login_rate_limit", "No login rate limit",
              "Unlimited password or OTP attempts"),
        Check("no_page_size_limit", "No page-size limit",
              "Asking for a huge page returns the whole table"),
    ]
}

# The checks our notes target can currently demonstrate (it has a flag for each).
FIRST_FOUR = ("object_level_access", "missing_auth", "mass_assignment", "excessive_data")
