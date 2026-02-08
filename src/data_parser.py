import logging
import time
import os
import matplotlib.pyplot as plt
import numpy as np
import csv

logging.basicConfig(level = logging.INFO)

DATA_DIR = "data"
CSV_NAME = "spectral_log.csv"

class SpectralAnalysis:
    def __init__(self):
        self.data = {
            "Violet": 0,
            "Indigo": 0,
            "Blue": 0,
            "Cyan": 0,
            "Green": 0,
            "Yellow": 0,
            "Orange": 0,
            "Red": 0,
            "CLR": 1,
            "NIR": 0,
            "SENSOR": 0,
        }

        # Approximate AS7341 centre wavelengths (nm)
        self.wavelengths = {
            "Violet": 405,
            "Indigo": 425,
            "Blue": 450,
            "Cyan": 475,
            "Green": 515,
            "Yellow": 555,
            "Orange": 590,
            "Red": 630
        }

        self._timestamp = None
        self._normalised = None
        self._board_id = None

        # Thresholds etc
        # Data structure: [DATA] F1=1,F2=5,F3=6,F4=11,F5=16,F6=23,F7=35,F8=31,CLR=6,NIR=0,SENSOR=1-16

    def _rgb_to_hex(self, rgb):
        r, g, b = [int(np.clip(v, 0, 255)) for v in rgb]
        return f"#{r:02X}{g:02X}{b:02X}"

    def parse_new_data(self, input: str, board_id: str | None = None):
        result = input.replace("[DATA] ", "")
        results = result.split(',')

        for i, r in enumerate(self.data):
            self.data[r] = int(results[i].split('=')[1]) # take number only

        self._timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        self._normalised = False
        self._board_id = board_id # reset to None if not given

    def normalise_data(self):
        CLR = self.data["CLR"]

        if CLR <= 0:
            raise ValueError("CLR must be > 0 for normalisation")
        
        # Normalise F1 to F8 only - leave CLR / NIR
        for band in self.wavelengths:
            self.data[band] = round(100 * self.data[band] / CLR, 3)

        self._normalised = True

    def _estimate_rgb_from_bands(self):
        """
        Best-guess colour from the 8 normalised bands.
        This is NOT colorimetrically accurate (no CIE matching functions here),
        but it produces a stable, intuitive "measured colour" for UI/plots.
        """
        # Pull bands (assumes already normalised by CLR)
        V = float(self.data["Violet"])
        I = float(self.data["Indigo"])
        B = float(self.data["Blue"])
        C = float(self.data["Cyan"])
        G = float(self.data["Green"])
        Y = float(self.data["Yellow"])
        O = float(self.data["Orange"])
        R = float(self.data["Red"])

        # Heuristic mapping of spectral bands -> RGB contributions
        # (weights chosen for plausibility + stability)
        r = (1.00 * R) + (0.70 * O) + (0.35 * Y) + (0.10 * V)
        g = (0.15 * C) + (1.00 * G) + (0.85 * Y) + (0.25 * O)
        b = (1.00 * B) + (0.65 * I) + (0.35 * V) + (0.25 * C)

        rgb = np.array([r, g, b], dtype=float)

        # Normalise to max=1 to keep “colour” independent of brightness
        m = float(np.max(rgb))
        if m <= 1e-12:
            rgb = np.array([0.0, 0.0, 0.0], dtype=float)
        else:
            rgb = rgb / m

        # Optional gamma-ish tweak for nicer perceived colour (not strict sRGB)
        gamma = 1.0 / 2.2
        rgb = np.power(np.clip(rgb, 0.0, 1.0), gamma)

        rgb_255 = (rgb * 255.0).round().astype(int)
        return rgb_255, self._rgb_to_hex(rgb_255)
    
    def plot_normalised_spectrum(
        self,
        save: bool = True,
        show_band_labels_top: bool = True
    ):
        if not self._normalised:
            self.normalise_data()

        # Base data (8 bands only)
        bands = list(self.wavelengths.keys())
        x = np.array([self.wavelengths[b] for b in bands], dtype=float)
        y = np.array([float(self.data[b]) for b in bands], dtype=float)

        # Estimate a representative colour from bands
        rgb, hex_color = self._estimate_rgb_from_bands()

        # Output directory
        os.makedirs(DATA_DIR, exist_ok=True)

        fig, ax = plt.subplots(figsize=(8, 4))

        # Smooth curve in "measured colour"
        ax.plot(x, y, linewidth=2.5, color=hex_color)

        # Original sample points for truth
        ax.scatter(x, y, s=20, color=hex_color)

        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Normalised Intensity (%)")
        ax.set_ylim(0, 105)
        ax.grid(True)
        ax.set_title(f"Normalised Spectrum (colour ≈ {hex_color})")

        # Optional top axis with band labels
        if show_band_labels_top:
            ax_top = ax.secondary_xaxis('top')
            ax_top.set_xticks(x)
            ax_top.set_xticklabels(bands)
            ax_top.set_xlabel("Spectral Band")
            ax_top.tick_params(axis='x', rotation=25)

        if save:
            filename = f"spectrum_{self._timestamp}_{self._board_id}.png"
            filepath = os.path.join(DATA_DIR, filename)
            plt.savefig(filepath, dpi=150, bbox_inches="tight")

        plt.close(fig)

        return rgb, hex_color
    
    def _csv_path(self) -> str:
        os.makedirs(DATA_DIR, exist_ok=True)
        return os.path.join(DATA_DIR, CSV_NAME)

    def _csv_headers(self):
        # Order is explicit and stable
        bands = list(self.wavelengths.keys())
        return (
            ["timestamp", "board_id", "sensor", "hex_color"]
            + [f"{b}_%" for b in bands]
            + ["CLR_raw", "NIR_raw"]
        )

    def append_to_csv(self, hex_color: str | None = None) -> str:
        """
        Append a single row to ./data/<filename>.

        Stores:
          - timestamp
          - hex_color (either provided, or computed from current normalised bands)
          - normalised band values (Violet..Red)
          - raw CLR and raw NIR (cached at parse time)

        Returns the CSV filepath.
        """
        if not self._normalised:
            self.normalise_data()

        if hex_color is None:
            _, hex_color = self._estimate_rgb_from_bands()

        bands = list(self.wavelengths.keys())
        row = {
            "timestamp": self._timestamp,
            "board_id": self._board_id,
            "sensor": int(self.data["SENSOR"]),
            "hex_color": hex_color,
            **{f"{b}_%": float(self.data[b]) for b in bands},
            "CLR_raw": int(self.data["CLR"]),
            "NIR_raw": int(self.data["NIR"]),
        }

        csv_path = self._csv_path()
        headers = self._csv_headers()
        file_exists = os.path.exists(csv_path)

        # Create file with header if missing / empty
        write_header = (not file_exists) or (os.path.getsize(csv_path) == 0)

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        return csv_path
