"""Research oceanographic collection and marine influence contracts."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from oceanography.core.config import ConfigDocument
from oceanography.core.config.common_areas import bbox_for_area

DEFAULT_CONFIG = "config/data/environment_oceanographic.yaml"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Satellite(Strict):
    dataset: str
    variable: str
    units: str
    resolution: Literal[5, 6]
    altitude: bool = False
    quality_variable: str | None = None
    quality_min: int = 4
    interpretation: str


class Gauge(Strict):
    provider: Literal["ECCC", "USGS"]
    station: str
    name: str
    mouth_lon: float = Field(ge=-180, le=180)
    mouth_lat: float = Field(ge=-90, le=90)
    mouth_reference: str
    mapping_status: Literal["research_approximate", "source_mouth"]


class TideStation(Strict):
    provider: Literal["CHS", "NOAA"]
    station: str


class OceanConfig(Strict):
    schema_version: Literal[1] = 1
    area: str = "model_area"
    raw_dir: str = "data/raw/environment/oceanographic"
    processed_dir: str = "data/processed/domain/environmental_layer/oceanographic"
    report_dir: str = "outputs/domains/environmental_layer/oceanographic"
    support_dir: str = "data/processed/domain/environmental_layer/seascape/spatial_support"
    satellite_base: str = "https://polarwatch.noaa.gov/erddap"
    salish_base: str = "https://salishsea.eos.ubc.ca/erddap"
    current_u_dataset: str = "ubcSSg3DuGridFields1hV21-11"
    current_v_dataset: str = "ubcSSg3DvGridFields1hV21-11"
    current_geometry_dataset: str = "ubcSSnBathymetryV21-08"
    offshore_current_base: str = "https://ncss.hycom.org/thredds/ncss/grid/GLBy0.08/expt_93.0/uv3z"
    tide_model_url: str = (
        "https://www.bio.gc.ca/science/research-recherche/ocean/webtide/Application/Install/InstData/Data/Unix/WebTide_ne_pac_data_0_7.sh"
    )
    current_interval_hours: Literal[1, 2, 3, 4, 6, 8, 12] = 4
    tide_decay_km: list[float] = Field(default_factory=lambda: [20.0, 40.0])
    river_decay_km: list[float] = Field(default_factory=lambda: [10.0, 25.0, 50.0])
    kernel_cutoff_multiples: float = Field(default=3.0, gt=0, le=5)
    seed_snap_max_km: float = Field(default=8.0, gt=0, le=10)
    seed_shore_tolerance_m: float = Field(default=100.0, ge=0, le=200)
    mouth_coast_snap_max_m: float = Field(default=1000.0, ge=0, le=1500)
    tide_coast_snap_max_m: float = Field(default=200.0, ge=0, le=300)
    productivity_window_days: Literal[7] = 7
    productivity_min_valid_days: int = Field(default=1, ge=1, le=7)
    min_tide_samples: int = Field(default=24, ge=12, le=24)
    satellites: dict[Literal["ocean_temperature", "productivity"], Satellite]
    tides: list[TideStation]
    rivers: list[Gauge]

    @field_validator("raw_dir", "processed_dir", "report_dir", "support_dir")
    @classmethod
    def relative_path(cls, value):
        if Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("Use workspace-relative paths without parent traversal")
        return value

    @field_validator("tide_decay_km", "river_decay_km")
    @classmethod
    def scales(cls, value):
        if not value or any(x <= 0 or x > 100 for x in value) or len(set(value)) != len(value):
            raise ValueError("Require distinct positive scales <= 100 km")
        return value

    @property
    def bbox(self):
        return bbox_for_area(self.area)


def load(path=DEFAULT_CONFIG):
    doc = ConfigDocument.load(path)
    return doc, doc.validate_as(OceanConfig)
