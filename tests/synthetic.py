"""Synthetic Berlin-like weather for tests and development only.

Never used for published results: the real inputs come from
``scripts/download_data.py``. Prices can be passed in (e.g. real SMARD
data) or are generated with a daily shape.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LATITUDE = np.radians(52.475)


def _tilted_irradiance(index: pd.DatetimeIndex, cloudiness: np.ndarray, azimuth_deg: float,
                       tilt_deg: float = 10.0) -> np.ndarray:
    doy = index.dayofyear.to_numpy()
    solar_hour = index.hour.to_numpy() + 0.5 + 13.3 / 15.0  # UTC -> local solar time
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + doy) / 365)
    hour_angle = np.radians(15.0 * (solar_hour - 12.0))
    sin_elev = (np.sin(LATITUDE) * np.sin(decl)
                + np.cos(LATITUDE) * np.cos(decl) * np.cos(hour_angle))
    sin_elev = np.clip(sin_elev, 0.0, None)
    elev = np.arcsin(sin_elev)
    sun_az = np.arctan2(np.sin(hour_angle),
                        np.cos(hour_angle) * np.sin(LATITUDE) - np.tan(decl) * np.cos(LATITUDE))
    tilt, panel_az = np.radians(tilt_deg), np.radians(azimuth_deg)
    cos_inc = (np.sin(elev) * np.cos(tilt)
               + np.cos(elev) * np.sin(tilt) * np.cos(sun_az - panel_az))
    clear_ghi = 1000.0 * sin_elev**1.15
    direct_share = 0.75 * (1.0 - cloudiness)
    ghi = clear_ghi * (1.0 - 0.7 * cloudiness)
    beam = ghi * direct_share / np.maximum(sin_elev, 0.05) * np.clip(cos_inc, 0.0, None)
    diffuse = ghi * (1.0 - direct_share) * (1.0 + np.cos(tilt)) / 2.0
    return np.where(sin_elev > 0.0, beam + diffuse, 0.0), ghi


def synthetic_snapshot(year: int = 2024, prices: pd.Series | None = None,
                       seed: int = 7) -> pd.DataFrame:
    """A frame in the download script's format (radiation = preceding-hour mean)."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="1h", tz="UTC",
                          inclusive="left")
    days = len(index) // 24
    doy = index.dayofyear.to_numpy()
    daily_anomaly = np.repeat(np.convolve(rng.normal(0, 3.0, days + 6), np.ones(7) / 7 * 2.2,
                                          "same")[3:3 + days], 24)[: len(index)]
    daily_anomaly = np.pad(daily_anomaly, (0, len(index) - len(daily_anomaly)), mode="edge")
    temp = (9.8 - 9.5 * np.cos(2 * np.pi * (doy - 15) / 365)
            + 4.0 * np.sin(2 * np.pi * (index.hour.to_numpy() - 9) / 24) + daily_anomaly)
    cloud_days = np.clip(rng.beta(1.3, 1.1, days + 1), 0.0, 1.0)
    cloudiness = np.repeat(cloud_days, 24)[: len(index)]
    east, ghi = _tilted_irradiance(index, cloudiness, -90.0)
    west, _ = _tilted_irradiance(index, cloudiness, 90.0)
    forecast_cloud = np.clip(cloudiness + rng.normal(0, 0.15, len(index)), 0, 1)
    east_fc, _ = _tilted_irradiance(index, forecast_cloud, -90.0)
    west_fc, _ = _tilted_irradiance(index, forecast_cloud, 90.0)

    frame = pd.DataFrame(index=index)
    if prices is None:
        shape = 90 + 30 * np.sin(2 * np.pi * (index.hour.to_numpy() - 13) / 24)
        prices = pd.Series(shape + rng.normal(0, 15, len(index)), index=index)
    frame["price_eur_mwh"] = prices.reindex(index).interpolate().bfill().ffill()
    frame["temp_c"] = temp
    radiation = {"ghi_wm2": ghi, "gti_east_wm2": east, "gti_west_wm2": west,
                 "gti_east_fc_wm2": east_fc, "gti_west_fc_wm2": west_fc}
    for column, values in radiation.items():
        # Stamp each hour's mean at the hour's end, as Open-Meteo does.
        frame[column] = pd.Series(values, index=index).shift(1).fillna(0.0)
    frame["temp_fc_c"] = temp + rng.normal(0, 1.0, len(index))
    frame["forecast_lead_hours"] = 48
    frame.index.name = "timestamp_utc"
    return frame
