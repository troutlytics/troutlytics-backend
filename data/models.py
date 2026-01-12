from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, Boolean, Date, Float, TIMESTAMP, ForeignKey

# Create a SQLAlchemy base
Base = declarative_base()


class WaterLocation(Base):
    __tablename__ = 'water_location'
    id = Column(Integer, primary_key=True, autoincrement=True)
    original_html_name = Column(String, unique=True)  # what wdfw named
    water_name_cleaned = Column(String)  # the cleaned name after scraping
    latitude = Column(Float)
    longitude = Column(Float)
    directions = Column(String)
    created_at = Column(TIMESTAMP)
    derby_participant = Column(Boolean)



class StockingReport(Base):
    __tablename__ = 'stocking_report'
    id = Column(Integer, primary_key=True)
    stocked_fish = Column(Integer) # the amount of stocked fish per report. TODO: change to amount_stocked
    species = Column(String)
    weight = Column(Float)
    hatchery = Column(String)
    date = Column(Date)
    water_location_id = Column(Integer, ForeignKey('water_location.id'))
    water_location = relationship("WaterLocation")

    # Not currently using this, but is maintained. May be helpful in the future
    def to_dict(self):
        return {
            "date": self.date,
            "water_name_cleaned": self.water_location.water_name_cleaned if self.water_location else None,
            "stocked_fish": self.stocked_fish,
            "species": self.species,
            "hatchery": self.hatchery,
            "weight": self.weight,
            "latitude": self.water_location.latitude if self.water_location else None,
            "longitude": self.water_location.longitude if self.water_location else None,
            "directions": self.water_location.directions if self.water_location else None,
            "water_location_id": self.water_location_id,
            "water_location": self.water_location
        }


class DerbyParticipant(Base):
    __tablename__ = 'derby_participant'
    id = Column(Integer, primary_key=True)
    lake = Column(String) # TODO: use FK reference to 


class Utility(Base):
    __tablename__ = 'utility'
    id = Column(Integer, primary_key=True)
    updated = Column(Date)
    updated_at = Column(TIMESTAMP)
    run_started_at = Column(TIMESTAMP)
    run_finished_at = Column(TIMESTAMP)
    run_seconds = Column(Float)
    rows_scraped = Column(Integer)
    rows_payload = Column(Integer)
    rows_inserted = Column(Integer)
    water_locations_matched = Column(Integer)
    water_locations_created = Column(Integer)
    water_locations_blocked = Column(Integer)
    source_url = Column(String)
    scraper_version = Column(String)
    status = Column(String)
