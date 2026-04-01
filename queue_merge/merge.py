import numpy as np
import os
import pandas as pd
import glob
from astropy.coordinates import SkyCoord
import astropy.units as u

raw_dir = "/lustre/scratch/nimcclur/skyq/data/raw"

alias_dict = {
    "name": ["name", "target", "object", "source", "target_name"],
    "ra": ["ra", "raj2000", "ra_deg"],
    "dec": ["dec", "dej2000", "dec_deg"]
}

def data_directory():
	files = glob.glob(f"{raw_dir}/*.txt")
	return sorted(files)

def read_data(file):
	df = pd.read_csv(file, sep = r"\s+")
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
	df.rename(columns=rename_dict)
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
			print("missing columnns")
			continue
		df = read_data(filepath)
		df.columns = standardize(df.columns)
		master_list.append(df)

	if len(master_list) == 0:
		print("missing master list")
		return
	master_df = pd.concat(master_list, ignore_index=True)
	master_path = "/lustre/scratch/nimcclur/skyq/data/master.csv"
	master_df.to_csv(master_path, index=False)
	master_df = coords_change(master_path)
	return master_df

def coords_change(master_path):
	df = pd.read_csv(master_path)
	mask = df["ra"].astype(str).str.contains(":")
	
	if mask.any():
		ra = df.loc[mask, "ra"]
		dec = df.loc[mask, "dec"]
		coords = SkyCoord(ra=ra.values, dec=dec.values, unit=(u.hourangle, u.deg))
		df.loc[mask, "ra"] = coords.ra.deg
		df.loc[mask, "dec"] = coords.dec.deg
	df.to_csv(master_path, index=False)
	return df
