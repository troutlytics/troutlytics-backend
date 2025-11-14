# data/database.py

import os
from datetime import datetime, timedelta
from typing import Optional, Set, Tuple

from sqlalchemy import create_engine, exists, text
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
    def write_data(self, data):
        # For SQLite demo runs, rebuild
        if str(self.engine) == "Engine(sqlite:///data/sqlite.db)":
            Base.metadata.drop_all(self.engine)
            Base.metadata.create_all(self.engine)

        self.write_lake_data(data)
        self.write_utility_data()
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

    def write_utility_data(self):
        self.session.add(Utility(updated=datetime.now().astimezone().date()))