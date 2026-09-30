"""Bounded controls shared by the MWR request contract and numerical engine."""

XIRR_MIN_REQUEST_SCAN_STEPS = 32
XIRR_MAX_SCAN_STEPS = 2_048
XIRR_MAX_ITERATIONS = 512
XIRR_MAX_WORK_UNITS = 409_600


def xirr_solver_work_units(*, root_scan_steps: int, max_iter: int) -> int:
    """Return the deterministic caller-controlled scan/iteration work budget."""

    return root_scan_steps * max_iter


def xirr_solver_work_is_admitted(*, root_scan_steps: int, max_iter: int) -> bool:
    return xirr_solver_work_units(root_scan_steps=root_scan_steps, max_iter=max_iter) <= XIRR_MAX_WORK_UNITS
