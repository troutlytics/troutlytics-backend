# data/database.py

import os
from datetime import datetime, timedelta, date as dt_date
from statistics import median
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import create_engine, exists, func, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from data.models import WaterLocation, StockingReport, DerbyParticipant, Utility, Base


def _norm_text(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip().lower()
    return v if v else None


class DataBase:
    def __init__(self):
        # Load Database
        db_user = os.getenv("POSTGRES_USER")
        db_password = os.getenv("POSTGRES_PASSWORD")
        db_name = os.getenv("POSTGRES_DB")
        db_host = os.getenv("POSTGRES_HOST")
        db_port = os.getenv("POSTGRES_PORT", "5432")  # Default Postgres port

        if db_user and db_password and db_name and db_host:
            database_url = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'

            self.engine = create_engine(
                database_url,
                pool_pre_ping=True,
                pool_recycle=1800,
                connect_args={"connect_timeout": 20}
            )
        else:
            print("USING SQLITE DB")
            self.engine = create_engine(
                'sqlite:///data/sqlite.db',
                connect_args={"check_same_thread": False},
            )

        self.conn = self.engine.connect()

        # IMPORTANT: turn off autoflush to avoid query-invoked autoflush exceptions
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.session = self.Session()

        self.insert_counter = 0

    # -------- Reading helpers (unchanged) --------
    def get_stocked_lakes_data(
        self,
        end_date: datetime = datetime.now(),
        start_date: datetime = datetime.now() - timedelta(days=7)
    ):
        rows = (
            self.session
                .query(WaterLocation, StockingReport)
                .join(StockingReport, StockingReport.water_location_id == WaterLocation.id)
                .filter(StockingReport.date.between(start_date, end_date))
                .order_by(StockingReport.date.desc())
                .all()
        )

        result = []
        for water_loc, stocked in rows:
            rec = {
                "date": stocked.date.isoformat() if stocked.date else None,
                "water_name_cleaned": water_loc.water_name_cleaned,
                "stocked_fish": stocked.stocked_fish,
                "species": stocked.species,
                "hatchery": stocked.hatchery,
                "weight": stocked.weight,
                "derby_participant": water_loc.derby_participant,
                "water_location_id": water_loc.id,
                "latitude": water_loc.latitude,
                "longitude": water_loc.longitude,
                "directions": water_loc.directions,
            }
            result.append(rec)

        return result

    def get_hatchery_totals(self, end_date=datetime.now(), start_date=datetime.now() - timedelta(days=7)):
        query = """
          SELECT hatchery, SUM(stocked_fish) AS sum_1
          FROM stocking_report
          WHERE date BETWEEN :start_date AND :end_date
          GROUP BY hatchery
          ORDER BY sum_1 DESC
        """
        return self.conn.execute(text(query), {"start_date": start_date, "end_date": end_date}).fetchall()

    def get_total_stocked_by_date_data(self, end_date=datetime.now(), start_date=datetime.now() - timedelta(days=7)):
        query = """
            SELECT date, SUM(stocked_fish) AS sum_1
            FROM stocking_report
            WHERE date BETWEEN :start_date AND :end_date
            GROUP BY date
            ORDER BY date
        """
        rows = self.conn.execute(text(query), {"start_date": start_date, "end_date": end_date}).fetchall()

        if str(self.engine) == "Engine(sqlite:///data/sqlite.db)":
            rows = [(datetime.strptime(date_str, "%Y-%m-%d"), stocked_fish) for date_str, stocked_fish in rows]
        return rows

    def get_derby_lakes_data(self):
        return self.conn.execute(text("SELECT * FROM derby_participant")).fetchall()

    def get_unique_hatcheries(self):
        rows = self.conn.execute(text("SELECT DISTINCT hatchery FROM stocking_report ORDER BY hatchery")).fetchall()
        return [row[0] for row in rows]

    def get_hatchery_profile(self, hatchery_name: str, recent_limit: int = 10):
        query = (hatchery_name or "").strip()
        if not query:
            return {
                "query": hatchery_name,
                "resolved_hatchery": None,
                "match_strategy": "none",
                "match_count": 0,
                "matches": [],
                "summary": None,
                "top_waters": [],
                "species_breakdown": [],
                "yearly_totals": [],
                "monthly_totals": [],
                "recent_stocking_activity": [],
                "all_stocking_activity": [],
                "geo_bounds": None,
            }

        pattern = f"%{query.lower()}%"
        candidate_rows = (
            self.session.query(
                StockingReport.hatchery.label("hatchery"),
                func.count(StockingReport.id).label("stocking_events"),
                func.coalesce(func.sum(StockingReport.stocked_fish), 0).label("total_fish_stocked"),
            )
            .filter(StockingReport.hatchery.isnot(None))
            .filter(func.lower(StockingReport.hatchery).like(pattern))
            .group_by(StockingReport.hatchery)
            .order_by(
                func.coalesce(func.sum(StockingReport.stocked_fish), 0).desc(),
                func.count(StockingReport.id).desc(),
                StockingReport.hatchery.asc(),
            )
            .all()
        )

        matches = [
            {
                "hatchery": row.hatchery,
                "stocking_events": int(row.stocking_events or 0),
                "total_fish_stocked": int(row.total_fish_stocked or 0),
            }
            for row in candidate_rows
        ]

        if not matches:
            return {
                "query": query,
                "resolved_hatchery": None,
                "match_strategy": "none",
                "match_count": 0,
                "matches": [],
                "summary": None,
                "top_waters": [],
                "species_breakdown": [],
                "yearly_totals": [],
                "monthly_totals": [],
                "recent_stocking_activity": [],
                "all_stocking_activity": [],
                "geo_bounds": None,
            }

        exact_match = next((m for m in matches if (m["hatchery"] or "").lower() == query.lower()), None)
        resolved_hatchery = exact_match["hatchery"] if exact_match else matches[0]["hatchery"]
        match_strategy = "exact_case_insensitive" if exact_match else "best_partial_by_total_fish"

        rows = (
            self.session.query(WaterLocation, StockingReport)
            .join(StockingReport, StockingReport.water_location_id == WaterLocation.id)
            .filter(func.lower(StockingReport.hatchery) == resolved_hatchery.lower())
            .order_by(StockingReport.date.desc(), StockingReport.id.desc())
            .all()
        )

        def _coerce_date(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v.date()
            if isinstance(v, dt_date):
                return v
            if isinstance(v, str):
                try:
                    return datetime.strptime(v, "%Y-%m-%d").date()
                except ValueError:
                    return None
            return None

        def _iso(v):
            d = _coerce_date(v)
            return d.isoformat() if d else None

        def _safe_round(v: Optional[float], digits: int = 2):
            if v is None:
                return None
            return round(float(v), digits)

        total_fish_stocked = 0
        stocking_events = 0
        unique_waters = set()
        unique_species = set()
        fish_counts: List[int] = []
        weights: List[float] = []
        dates: List[dt_date] = []
        derby_stocking_events = 0
        unique_waters_with_coordinates = set()
        unique_derby_waters = set()

        water_totals: Dict[str, Dict[str, Any]] = {}
        species_totals: Dict[str, Dict[str, Any]] = {}
        yearly_totals: Dict[int, Dict[str, Any]] = {}
        monthly_totals: Dict[int, Dict[str, Any]] = {}
        all_stocking_activity: List[Dict[str, Any]] = []

        coordinate_points = set()

        for water_loc, stocked in rows:
            fish_stocked = int(stocked.stocked_fish or 0)
            stocking_events += 1
            total_fish_stocked += fish_stocked
            fish_counts.append(fish_stocked)

            event_date = _coerce_date(stocked.date)
            if event_date:
                dates.append(event_date)

            weight_value = float(stocked.weight) if stocked.weight is not None else None
            if weight_value is not None:
                weights.append(weight_value)

            water_name = water_loc.water_name_cleaned or "Unknown Water"
            species_name = stocked.species or "Unknown Species"
            unique_waters.add(water_name)
            unique_species.add(species_name)

            if water_loc.derby_participant:
                derby_stocking_events += 1
                unique_derby_waters.add(water_name)

            if water_loc.latitude is not None and water_loc.longitude is not None:
                lat = float(water_loc.latitude)
                lon = float(water_loc.longitude)
                coordinate_points.add((lat, lon))
                unique_waters_with_coordinates.add(water_name)

            event_record = {
                "date": _iso(stocked.date),
                "water_name": water_name,
                "species": species_name,
                "fish_stocked": fish_stocked,
                "weight": weight_value,
                "latitude": water_loc.latitude,
                "longitude": water_loc.longitude,
                "directions": water_loc.directions,
                "derby_participant": bool(water_loc.derby_participant),
            }
            all_stocking_activity.append(event_record)

            water_entry = water_totals.setdefault(
                water_name,
                {
                    "water_name": water_name,
                    "total_fish_stocked": 0,
                    "stocking_events": 0,
                    "first_stocking_date": None,
                    "most_recent_stocking_date": None,
                    "latitude": water_loc.latitude,
                    "longitude": water_loc.longitude,
                    "directions": water_loc.directions,
                    "derby_participant": bool(water_loc.derby_participant),
                    "species_set": set(),
                },
            )
            water_entry["total_fish_stocked"] += fish_stocked
            water_entry["stocking_events"] += 1
            water_entry["species_set"].add(species_name)

            if event_date:
                if not water_entry["first_stocking_date"] or event_date < water_entry["first_stocking_date"]:
                    water_entry["first_stocking_date"] = event_date
                if not water_entry["most_recent_stocking_date"] or event_date > water_entry["most_recent_stocking_date"]:
                    water_entry["most_recent_stocking_date"] = event_date

            species_entry = species_totals.setdefault(
                species_name,
                {
                    "species": species_name,
                    "total_fish_stocked": 0,
                    "stocking_events": 0,
                    "weights": [],
                },
            )
            species_entry["total_fish_stocked"] += fish_stocked
            species_entry["stocking_events"] += 1
            if weight_value is not None:
                species_entry["weights"].append(weight_value)

            if event_date:
                year_entry = yearly_totals.setdefault(
                    event_date.year,
                    {
                        "year": event_date.year,
                        "total_fish_stocked": 0,
                        "stocking_events": 0,
                        "waters_set": set(),
                        "species_set": set(),
                    },
                )
                year_entry["total_fish_stocked"] += fish_stocked
                year_entry["stocking_events"] += 1
                year_entry["waters_set"].add(water_name)
                year_entry["species_set"].add(species_name)

                month_entry = monthly_totals.setdefault(
                    event_date.month,
                    {
                        "month_number": event_date.month,
                        "month": event_date.strftime("%b"),
                        "total_fish_stocked": 0,
                        "stocking_events": 0,
                    },
                )
                month_entry["total_fish_stocked"] += fish_stocked
                month_entry["stocking_events"] += 1

        if coordinate_points:
            latitudes = [point[0] for point in coordinate_points]
            longitudes = [point[1] for point in coordinate_points]
            geo_bounds = {
                "min_latitude": min(latitudes),
                "max_latitude": max(latitudes),
                "min_longitude": min(longitudes),
                "max_longitude": max(longitudes),
                "center_latitude": _safe_round(sum(latitudes) / len(latitudes), 6),
                "center_longitude": _safe_round(sum(longitudes) / len(longitudes), 6),
            }
        else:
            geo_bounds = None

        average_weight = (sum(weights) / len(weights)) if weights else None
        average_fish_per_event = (total_fish_stocked / stocking_events) if stocking_events else None
        median_fish_per_event = median(fish_counts) if fish_counts else None
        first_recorded_stocking = min(dates).isoformat() if dates else None
        most_recent_stocking = max(dates).isoformat() if dates else None
        active_years = len({d.year for d in dates}) if dates else 0

        top_waters = []
        for data in water_totals.values():
            top_waters.append(
                {
                    "water_name": data["water_name"],
                    "total_fish_stocked": data["total_fish_stocked"],
                    "stocking_events": data["stocking_events"],
                    "first_stocking_date": data["first_stocking_date"].isoformat() if data["first_stocking_date"] else None,
                    "most_recent_stocking_date": data["most_recent_stocking_date"].isoformat() if data["most_recent_stocking_date"] else None,
                    "species": sorted(data["species_set"]),
                    "latitude": data["latitude"],
                    "longitude": data["longitude"],
                    "directions": data["directions"],
                    "derby_participant": data["derby_participant"],
                    "share_of_total_fish_pct": _safe_round(
                        (data["total_fish_stocked"] / total_fish_stocked) * 100 if total_fish_stocked else 0,
                        2,
                    ),
                }
            )
        top_waters.sort(
            key=lambda x: (-x["total_fish_stocked"], -x["stocking_events"], x["water_name"])
        )

        species_breakdown = []
        for data in species_totals.values():
            species_breakdown.append(
                {
                    "species": data["species"],
                    "total_fish_stocked": data["total_fish_stocked"],
                    "stocking_events": data["stocking_events"],
                    "average_weight": _safe_round(
                        sum(data["weights"]) / len(data["weights"]) if data["weights"] else None,
                        2,
                    ),
                    "share_of_total_fish_pct": _safe_round(
                        (data["total_fish_stocked"] / total_fish_stocked) * 100 if total_fish_stocked else 0,
                        2,
                    ),
                }
            )
        species_breakdown.sort(
            key=lambda x: (-x["total_fish_stocked"], -x["stocking_events"], x["species"])
        )

        yearly_summary = []
        for year in sorted(yearly_totals.keys()):
            data = yearly_totals[year]
            yearly_summary.append(
                {
                    "year": data["year"],
                    "total_fish_stocked": data["total_fish_stocked"],
                    "stocking_events": data["stocking_events"],
                    "unique_waters_served": len(data["waters_set"]),
                    "unique_species_stocked": len(data["species_set"]),
                    "average_fish_per_event": _safe_round(
                        data["total_fish_stocked"] / data["stocking_events"] if data["stocking_events"] else None,
                        2,
                    ),
                }
            )

        monthly_summary = []
        for month in sorted(monthly_totals.keys()):
            data = monthly_totals[month]
            monthly_summary.append(
                {
                    "month_number": data["month_number"],
                    "month": data["month"],
                    "total_fish_stocked": data["total_fish_stocked"],
                    "stocking_events": data["stocking_events"],
                    "average_fish_per_event": _safe_round(
                        data["total_fish_stocked"] / data["stocking_events"] if data["stocking_events"] else None,
                        2,
                    ),
                }
            )

        recent_limit = max(1, int(recent_limit or 10))
        recent_stocking_activity = all_stocking_activity[:recent_limit]

        largest_stocking_event = max(all_stocking_activity, key=lambda x: x["fish_stocked"], default=None)

        summary = {
            "coverage_statement": (
                f"Total coverage based on {stocking_events} stocking events "
                f"across {len(unique_waters)} waters."
            ),
            "total_fish_stocked": total_fish_stocked,
            "stocking_events": stocking_events,
            "unique_waters_served": len(unique_waters),
            "unique_species_stocked": len(unique_species),
            "average_fish_weight": _safe_round(average_weight, 2),
            "average_fish_per_event": _safe_round(average_fish_per_event, 2),
            "median_fish_per_event": _safe_round(float(median_fish_per_event), 2) if median_fish_per_event is not None else None,
            "first_recorded_stocking": first_recorded_stocking,
            "most_recent_stocking": most_recent_stocking,
            "active_years": active_years,
            "average_events_per_year": _safe_round(
                stocking_events / active_years if active_years else None,
                2,
            ),
            "waters_with_coordinates": len(unique_waters_with_coordinates),
            "derby_stocking_events": derby_stocking_events,
            "derby_waters_served": len(unique_derby_waters),
            "largest_stocking_event": largest_stocking_event,
        }

        return {
            "query": query,
            "resolved_hatchery": resolved_hatchery,
            "match_strategy": match_strategy,
            "match_count": len(matches),
            "matches": matches,
            "summary": summary,
            "top_waters": top_waters,
            "species_breakdown": species_breakdown,
            "yearly_totals": yearly_summary,
            "monthly_totals": monthly_summary,
            "recent_stocking_activity": recent_stocking_activity,
            "all_stocking_activity": all_stocking_activity,
            "geo_bounds": geo_bounds,
        }

    def get_date_data_updated(self):
        return self.conn.execute(text("SELECT updated FROM utility ORDER BY id DESC LIMIT 1")).scalar()

    def get_water_location(self, original_html_name):
        # match exactly on stored original_html_name (you already normalize in scraper)
        return (
            self.session.query(WaterLocation)
            .filter(WaterLocation.original_html_name.ilike(original_html_name))
            .first()
        )

    # -------- Write entry points --------
    def write_data(self, data, utility_meta=None):
        # For SQLite demo runs, rebuild
        if str(self.engine) == "Engine(sqlite:///data/sqlite.db)":
            Base.metadata.drop_all(self.engine)
            Base.metadata.create_all(self.engine)

        self.write_lake_data(data)
        self.write_utility_data(utility_meta=utility_meta)
        self.session.commit()
        self.session.close()

    # -------- Utilities --------
    def record_exists(self, model, **kwargs):
        return self.session.query(
            exists().where(*(getattr(model, k) == v for k, v in kwargs.items()))
        ).scalar()

    def insert_water_location(self, original_html_name, water_name_cleaned, latitude, longitude, directions, derby_participant):
        if self.record_exists(WaterLocation, original_html_name=original_html_name):
            print(f"Skipping insert — Water location '{original_html_name}' already exists.")
            return
        new_location = WaterLocation(
            original_html_name=original_html_name,
            water_name_cleaned=water_name_cleaned,
            latitude=latitude,
            longitude=longitude,
            directions=directions,
            created_at=datetime.now(),
            derby_participant=derby_participant,
        )
        self.session.add(new_location)
        self.session.commit()
        print(f"✅ Inserted new water location: {original_html_name}")

    # -------- Dedup support --------
    def _preload_existing_report_keys(self) -> Set[Tuple]:
        """
        Natural key: (date, water_location_id, species, hatchery, stocked_fish)
        All text normalized to lowercase/trim on load.
        """
        rows = self.session.query(
            StockingReport.date,
            StockingReport.water_location_id,
            StockingReport.species,
            StockingReport.hatchery,
            StockingReport.stocked_fish
        ).all()

        keys = set()
        for d, wl_id, sp, hat, cnt in rows:
            keys.add((d, wl_id, _norm_text(sp), _norm_text(hat), cnt))
        return keys

    def _insert_stocking_upsert_pg(self, payload: dict, use_constraint: bool = True) -> bool:
        """
        Returns True if a row was inserted, False if it conflicted and did nothing.
        """
        stmt = pg_insert(StockingReport.__table__).values(payload)

        stmt = stmt.on_conflict_do_nothing(
            index_elements=['date', 'species', 'hatchery', 'stocked_fish']
        )

        # Ask Postgres to return the id only when an insert happened
        stmt = stmt.returning(StockingReport.id)

        res = self.session.execute(stmt)
        
        inserted_pk = res.scalar_one_or_none()
        return inserted_pk is not None

    # -------- Main write path --------
    def write_lake_data(self, data):
        # Preload keys already in DB and dedup within this run
        existing_keys = self._preload_existing_report_keys()
        seen_this_run: Set[Tuple] = set()

        # Simple cache for WLs we resolve during this run
        wl_cache = {}

        for lake_data in data:
            original_html_name = lake_data['original_html_name']
            wl_cache_key = (original_html_name or "").strip().lower()

            water_location = wl_cache.get(wl_cache_key)
            if not water_location:
                # avoid autoflush while we query
                with self.session.no_autoflush:
                    water_location = self.get_water_location(original_html_name)

            # Create WL only if allowed (scraper decides to include or skip rows without WL)
            if not water_location and os.getenv("SCRAPER_ALLOW_CREATE_WATER_LOCATION", "false").lower() in ("1", "true", "yes"):
                water_location = WaterLocation(
                    original_html_name=original_html_name,
                    water_name_cleaned=lake_data['water_name_cleaned'],
                    latitude=lake_data['latitude'],
                    longitude=lake_data['longitude'],
                    directions=lake_data['directions'],
                    created_at=datetime.now(),
                    derby_participant=lake_data.get('derby_participant', False)
                )
                self.session.add(water_location)
                self.session.flush()  # assign id

            if not water_location:
                # If we still don't have a WL, skip this row (prevents orphan/duplicate WLs)
                continue

            wl_cache[wl_cache_key] = water_location

            species = lake_data.get('species')
            hatchery = lake_data.get('hatchery')

            # Build natural key
            nk = (lake_data['date'], water_location.id, species, hatchery, lake_data['stocked_fish'])

            # Skip if duplicate in DB or within this run
            if nk in existing_keys or nk in seen_this_run:
                # print(f"Skip dup: {nk}")
                continue

            # Build insert payload
            payload = {
                "stocked_fish": lake_data['stocked_fish'],
                "date": lake_data['date'],
                "weight": lake_data.get('weight'),
                "species": species,
                "hatchery": hatchery,
                "water_location_id": water_location.id,
            }

            inserted = False
            inserted = self._insert_stocking_upsert_pg(payload, use_constraint=True)

            if inserted:
                self.insert_counter += 1
                seen_this_run.add(nk)

        print(f'There were {self.insert_counter} entries added to {str(StockingReport.__tablename__)}')

    def write_utility_data(self, utility_meta=None):
        utility_meta = utility_meta or {}
        run_started_at = utility_meta.get("run_started_at")
        run_finished_at = utility_meta.get("run_finished_at") or datetime.now().astimezone()
        run_seconds = utility_meta.get("run_seconds")
        if run_seconds is None and run_started_at:
            run_seconds = (run_finished_at - run_started_at).total_seconds()

        self.session.add(
            Utility(
                updated=run_finished_at.date(),
                updated_at=run_finished_at,
                run_started_at=run_started_at,
                run_finished_at=run_finished_at,
                run_seconds=run_seconds,
                rows_scraped=utility_meta.get("rows_scraped"),
                rows_payload=utility_meta.get("rows_payload"),
                rows_inserted=utility_meta.get("rows_inserted", self.insert_counter),
                water_locations_matched=utility_meta.get("water_locations_matched"),
                water_locations_created=utility_meta.get("water_locations_created"),
                water_locations_blocked=utility_meta.get("water_locations_blocked"),
                source_url=utility_meta.get("source_url"),
                scraper_version=utility_meta.get("scraper_version"),
                status=utility_meta.get("status", "success"),
            )
        )
