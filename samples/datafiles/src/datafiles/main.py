from pathlib import Path
import sysconfig
from PIL import Image


def main():
    data_path = Path(sysconfig.get_path("data"))
    img_path = data_path / "ebi.jpeg"
    img = Image.open(img_path)

    print(f"Path: {img_path!s}")
    print(f"Size: {img.size}")

    img.show()

if __name__ == "__main__":
    main()
