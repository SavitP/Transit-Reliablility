"""Capture real data once and save it as test fixtures. Tests then never touch the internet.

Run (rarely, e.g. after Metro changes its feed format):  python -m tests.make_fixtures
It saves three live snapshots 30s apart, plus a schedule trimmed to just the trips
in those snapshots (the full schedule is 10 MB; this keeps the repo small).
"""

import csv
import io
import time
import zipfile
from pathlib import Path

from fetch_vehicles import VEHICLE_POSITIONS_URL, decode_feed, download_feed
from schedule import ensure_schedule_downloaded

FIXTURES = Path(__file__).parent / "fixtures"
KEEP_FILES = ["agency.txt", "routes.txt", "stops.txt", "trips.txt", "stop_times.txt"]


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    trip_ids = set()
    for i in range(3):
        raw = download_feed(VEHICLE_POSITIONS_URL)
        (FIXTURES / f"vehiclepositions_{i}.pb").write_bytes(raw)
        trip_ids |= {e.vehicle.trip.trip_id for e in decode_feed(raw).entity if e.vehicle.trip.trip_id}
        print(f"saved snapshot {i}")
        if i < 2:
            time.sleep(30)

    with zipfile.ZipFile(ensure_schedule_downloaded()) as src, \
         zipfile.ZipFile(FIXTURES / "schedule_trimmed.zip", "w", zipfile.ZIP_DEFLATED) as dst:
        for name in KEEP_FILES:
            with src.open(name) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, "utf-8-sig"))
                out = io.StringIO()
                writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
                writer.writeheader()
                for row in reader:
                    if "trip_id" not in row or row["trip_id"] in trip_ids:
                        writer.writerow(row)
                dst.writestr(name, out.getvalue())
    print(f"saved trimmed schedule with {len(trip_ids)} trips")


if __name__ == "__main__":
    main()
