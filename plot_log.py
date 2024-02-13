#!/usr/bin/env python3

import click
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

k = 0.025
d = 40

# very simple predictive model of roast temp => bean temp
# based on Newtons law of cooling
def predict_bean_temps(df, initial_temp):
	predicted_temps = [initial_temp]
	for i in range(1, len(df)):
		delta_temp = k * (df.iloc[i-1]["temperature °C"] - predicted_temps[i-1] - d)
		delta_time = df.iloc[i]["roast time"] - df.iloc[i-1]["roast time"]
		new_temp = predicted_temps[-1] + delta_temp * delta_time
		predicted_temps.append(new_temp)
	df["predicted bean temperature °C"] = predicted_temps

@click.command()
@click.option("--ikawa-log", required=True, type=str, help="Path to the Ikawa log file.")
@click.option("--esp32-log", type=str, default="", help="Path to the ESP32 log file.")
@click.option("--first-crack", type=int, help="Time of the first crack event.")
@click.option("--output", type=str, help="Output file path for saving the plot.")
@click.option("--predict-bean-temp", is_flag=True, help="Flag to calculate and show predicted bean temperature.")
def main(ikawa_log, esp32_log, first_crack, output, predict_bean_temp):
	ikawa_df = pd.read_csv(ikawa_log, skipinitialspace=True)
	filtered_ikawa_df = ikawa_df[(ikawa_df["roaster state"] == "ROASTING") | (ikawa_df["roaster state"] == "COOLDOWN")].copy()
	filtered_ikawa_df["real time"] = pd.to_datetime(filtered_ikawa_df["real time"]).dt.tz_localize(None)

	ikawa_start_time = filtered_ikawa_df.iloc[0]["real time"]
	ikawa_start_roast_time = filtered_ikawa_df.iloc[0]["roast time"]

	plt.figure(figsize=(10, 6))
	plt.plot(filtered_ikawa_df["roast time"], filtered_ikawa_df["setpoint target temperature °C"], linestyle="-", color="gray", label="Setpoint Temperature")
	plt.plot(filtered_ikawa_df["roast time"], filtered_ikawa_df["temperature °C"], linestyle="-", color="red", label="Inlet Temperature")

	if predict_bean_temp:
		predict_bean_temps(filtered_ikawa_df, 20)
		plt.plot(filtered_ikawa_df["roast time"], filtered_ikawa_df["predicted bean temperature °C"], linestyle="--", color="purple", label="Predicted Bean Temperature")

	if esp32_log:
		esp32_df = pd.read_csv(esp32_log, skipinitialspace=True)
		esp32_df["real time"] = pd.to_datetime(esp32_df["real time"]).dt.tz_localize(None)

		abs_time_diff = (esp32_df["real time"] - ikawa_start_time).abs()
		closest_match_index = abs_time_diff.idxmin()
		closest_system_time = esp32_df.iloc[closest_match_index]["system time"]
		time_offset = closest_system_time - ikawa_start_roast_time
		esp32_df["roast time"] = esp32_df["system time"] - time_offset

		start_time, end_time = filtered_ikawa_df["roast time"].min() - 30, filtered_ikawa_df["roast time"].max() + 30
		esp32_filtered_df = esp32_df[(esp32_df["roast time"] >= start_time) & (esp32_df["roast time"] <= end_time)]

		plt.plot(esp32_filtered_df["roast time"], esp32_filtered_df["temperature °C"], linestyle="-", color="orange", label="ESP32 Temperature")

	if first_crack:
		plt.axvline(x=first_crack, color="green", linestyle=":", label="First Crack")

	plt.xlabel("Time")
	plt.ylabel("Temperature (°C)")
	plt.legend()
	plt.grid(True)
	plt.ylim(bottom=100)
	plt.gca().xaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{int(x // 60)}:{int(x % 60):02d}"))

	if output:
		plt.savefig(output, format="svg")
	else:
		plt.show()

if __name__ == "__main__":
	main()
