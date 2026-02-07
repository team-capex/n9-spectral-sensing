import logging
import time
import os
import matplotlib.pyplot as plt

logging.basicConfig(level = logging.INFO)

DATA_DIR = "data"

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
            "NIR": 0
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

        # Thresholds etc
        # Data structure: [DATA] F1=1,F2=5,F3=6,F4=11,F5=16,F6=23,F7=35,F8=31,CLR=6,NIR=0

    def parse_new_data(self, input: str):
        result = input.replace("[DATA] ", "")
        results = result.split(',')

        for i, r in enumerate(self.data):
            self.data[r] = int(results[i].split('=')[1]) # take number only

        self._normalised = False

    def normalise_data(self):
        CLR = self.data["CLR"]

        if CLR <= 0:
            raise ValueError("CLR must be > 0 for normalisation")
    
        for band in self.data:
            self.data[band] = self.data[band] / CLR

        self._normalised = True

    def plot_normalised_spectrum(self, save: bool = True):
        if not self._normalised:
            self.normalise_data()

        wavelengths = []
        intensities = []
        labels = []

        for band, wl in self.wavelengths.items():
            wavelengths.append(wl)
            intensities.append(100*self.data[band])
            labels.append(band)

        # Ensure output directory exists
        os.makedirs(DATA_DIR, exist_ok=True)

        fig, ax = plt.subplots(figsize=(8, 4))

        # Main spectrum plot
        ax.plot(wavelengths, intensities, marker='o')
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Normalised Intensity (%)")
        ax.set_ylim(0, 105)
        ax.grid(True)

        # Secondary x-axis (top) for colour names
        ax_top = ax.secondary_xaxis('top')
        ax_top.set_xticks(wavelengths)
        ax_top.set_xticklabels(labels)
        ax_top.set_xlabel("Spectral Band")

        ax.set_title("Normalised Spectral Response")

        if save:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"spectrum_{timestamp}.png"
            filepath = os.path.join(DATA_DIR, filename)
            plt.savefig(filepath, dpi=150, bbox_inches="tight")

        plt.close()

    
