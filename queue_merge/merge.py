import numpy as np
import os
import pandas as pd
import glob
from pathlib import Path
from astropy.coordinates import SkyCoord
import astropy.units as u

PROJECT_DIR = Path.cwd()
raw_dir = PROJECT_DIR / "data" / "raw"
master_path = PROJECT_DIR / "data" / "master.csv"
SUPPORTED_SUFFIXES = {".csv", ".tsv", ".txt"}

alias_dict = {
    "name": ["name", "target", "object", "source", "target_name"],
    "ra": ["ra", "raj2000", "ra_deg"],
    "dec": ["dec", "dej2000", "dec_deg"]
}

def data_directory():
	files = [
		str(path) for path in raw_dir.iterdir()
		if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
	]
	return sorted(files)

def read_data(file):
	path = Path(file)

	if path.suffix.lower() == ".csv":
		df = pd.read_csv(path)
	else:
		df = pd.read_csv(path, sep = r"\s+")

	return df

def read_columns(file):
	df = read_data(file)
	columns = df.columns.to_list()
	return columns

def standardize(columns):
	normalized = []
	for col in columns:
		new_col = col.strip().lower()
		normalized.append(new_col)
	return normalized

def alias_check(df):
	df.columns = standardize(df.columns)
	rename_dict = {}
	for canonical, aliases in alias_dict.items():
		for alias in aliases:
			if alias in df.columns:
				rename_dict[alias] = canonical
	df = df.rename(columns=rename_dict)
	return df

def check_cols(normalized):
	required = ["ra", "dec", "name"]
	for col in required:
		if col not in normalized:
			return False
	return True

def make_master():
	files = data_directory()
	master_list = []

	for filepath in files:
		df = read_data(filepath)
		df = alias_check(df)
		normalized = standardize(df.columns)
		ok = check_cols(normalized)
		if not ok:
			print(
				f"[merge] Skipping {os.path.basename(filepath)}: "
				f"missing required columns. Found columns: {normalized}",
				flush=True,
			)
			continue
		master_list.append(df)

	if len(master_list) == 0:
		print("[merge] No valid target sheets found", flush=True)
		return
	master_df = pd.concat(master_list, ignore_index=True)
	master_path.parent.mkdir(parents=True, exist_ok=True)
	master_df.to_csv(master_path, index=False)
	master_df = coords_change(master_path)
	rows_before = len(master_df)
	master_df = master_df.drop_duplicates(subset=["name", "ra", "dec"], keep="first")

	if len(master_df) != rows_before:
		print(
			f"[merge] Removed {rows_before - len(master_df)} duplicate targets",
			flush=True,
		)

	master_df.to_csv(master_path, index=False)
	return master_df

def coords_change(master_path):
	df = pd.read_csv(master_path)
	mask = df["ra"].astype(str).str.contains(":") | df["dec"].astype(str).str.contains(":")
	
	if mask.any():
		ra = df.loc[mask, "ra"]
		dec = df.loc[mask, "dec"]
		coords = SkyCoord(ra=ra.values, dec=dec.values, unit=(u.hourangle, u.deg))
		df.loc[mask, "ra"] = coords.ra.deg
		df.loc[mask, "dec"] = coords.dec.deg
	df.to_csv(master_path, index=False)
	return df
