"""NoiseModelling 6.0.0 command steps and run with metrics."""

import os
import sys
from pathlib import Path

from pipeline.metrics import run_step


def script_runner(nm_home: Path) -> Path:
    """Return the path to the NoiseModelling script runner executable."""
    if os.name == "nt":
        return Path(nm_home) / "bin" / "ScriptRunner.bat"
    return Path(nm_home) / "bin" / "ScriptRunner"


def build_steps(
    nm_home: Path,
    workspace: Path,
    inputs: dict,
    params: dict,
) -> list[tuple[str, list[str], str]]:
    """Build the list of NoiseModelling command steps.

    Each element is (name, argv, cwd).
    """
    r = str(script_runner(nm_home))
    ws = str(workspace)
    cwd = str(nm_home)

    steps: list[tuple[str, list[str], str]] = []

    # 1. Import DEM
    steps.append((
        "import_dem",
        [r, "-w", ws, "-s", "scripts/Import_and_Export/Import_Asc_File.groovy",
         "--pathFile", str(inputs["dem"]), "--inputSRID", "5514"],
        cwd,
    ))

    # 2-5. Import ground, buildings, sources, receivers
    import_table_map = [
        ("import_ground", "ground", "GROUND"),
        ("import_buildings", "buildings", "BUILDINGS"),
        ("import_sources", "sources", "SOURCES"),
        ("import_receivers", "receivers", "RECEIVERS"),
    ]
    for name, key, table in import_table_map:
        steps.append((
            name,
            [r, "-w", ws, "-s", "scripts/Import_and_Export/Import_File.groovy",
             "--pathFile", str(inputs[key]), "--inputSRID", "5514",
             "--tableName", table],
            cwd,
        ))

    # 6. Propagate noise
    fav = ",".join([str(params["favourable"])] * 16)
    steps.append((
        "propagate",
        [r, "-w", ws, "-s", "scripts/NoiseModelling/Noise_level_from_source.groovy",
         "--tableSources", "SOURCES",
         "--tableReceivers", "RECEIVERS",
         "--tableBuilding", "BUILDINGS",
         "--tableDEM", "DEM",
         "--tableGroundAbs", "GROUND",
         "--confMaxSrcDist", str(params["max_distance_m"]),
         "--confReflOrder", "0",
         "--confDiffVertical", "false",
         "--confDiffHorizontal", "true",
         "--confExportSourceId", "true",
         "--confHumidity", str(params["humidity_percent"]),
         "--confTemperature", str(params["temperature_c"]),
         "--confFavourableOccurrencesDefault", fav,
         "--confThreadNumber", str(params["threads"]),
         "--confMaxError", "0"],
        cwd,
    ))

    # 7. Export results
    steps.append((
        "export",
        [r, "-w", ws, "-s", "scripts/Import_and_Export/Export_Table.groovy",
         "--exportPath", str(inputs["result_csv"]),
         "--tableToExport", "RECEIVERS_LEVEL"],
        cwd,
    ))

    return steps


def run_steps(
    steps: list[tuple[str, list[str], str]],
    java: Path,
    metrics_csv: Path,
    watch_dir: Path,
    java_opts: str = "",
    timeout_s: int | None = None,
    prefix: str = "",
) -> list[dict]:
    """Run each step in order, recording metrics, stopping on first failure."""
    env = dict(os.environ)
    env["JAVACMD"] = str(java)
    env["JAVA_OPTS"] = java_opts

    rows: list[dict] = []
    for name, argv, cwd in steps:
        row = run_step(
            prefix + name,
            argv,
            watch_dir,
            metrics_csv,
            cwd=cwd,
            env=env,
            timeout_s=timeout_s,
        )
        rows.append(row)
        if row["exit_code"] != 0:
            break
    return rows
