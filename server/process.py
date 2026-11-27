"""Process record for one sticker: an image per stage, written as the stage ends.

process/1_photo.jpg   photo and the selected box
process/2_segment.jpg SAM 2.1 cutout (background dimmed, outline drawn), around the goods
process/3_depth.jpg   YOLO depth inside the cutout (near = warm), same crop
process/4_height.jpg  sticker height: rounded border + depth relief, shaded
process/5_sticker.jpg glossy sticker preview with highlight and shadow
process.jpg           the five stages side by side with labels
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parent / 'reference' / 'fonts' / 'NanumGgocNaeEum.ttf'
BACKGROUND = np.array([0.933, 0.969, 0.988])  # app sky #eef7fc
LABELS = {
    '1_photo': '1. 사진과 선택 영역',
    '2_segment': '2. SAM 2.1 누끼',
    '3_depth': '3. YOLO 깊이',
    '4_height': '4. 볼록 높이',
    '5_sticker': '5. 유광 스티커',
}


def to_image(rgb):
    return Image.fromarray((np.clip(rgb, 0, 1) * 255).round().astype(np.uint8))


class Recorder:
    def __init__(self, output: Path):
        self.folder = Path(output) / 'process'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.output = Path(output)
        self.stages = []
        self.crop = None

    def save(self, name, image):
        image.convert('RGB').save(self.folder / f'{name}.jpg', quality=90)
        self.stages.append(name)

    def photo(self, image, box):
        frame = image.convert('RGB').copy()
        if box:
            w, h = frame.size
            draw = ImageDraw.Draw(frame)
            width = max(2, round(max(w, h) / 160))
            draw.rectangle([box[0] * w, box[1] * h, box[2] * w, box[3] * h], outline=(34, 199, 160), width=width)
        self.save('1_photo', frame)

    def around(self, array):
        if self.crop is None:
            return array
        top, bottom, left, right = self.crop
        return array[top:bottom, left:right]

    def segment(self, image, alpha):
        ys, xs = np.nonzero(alpha > .5)
        h, w = alpha.shape
        margin = round(max(np.ptp(ys), np.ptp(xs)) * .15)
        self.crop = (max(ys.min() - margin, 0), min(ys.max() + margin + 1, h),
                     max(xs.min() - margin, 0), min(xs.max() + margin + 1, w))
        rgb = np.asarray(image.convert('RGB'), dtype=np.float64) / 255
        inside = alpha[..., None]
        view = rgb * inside + (rgb * 0.25 + 0.55) * (1 - inside)
        edge = cv2.morphologyEx((alpha > .5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
        view[edge] = [0.133, 0.78, 0.627]
        self.save('2_segment', to_image(self.around(view)))

    def depth(self, depth, alpha):
        inside = alpha > .5
        lo, hi = np.percentile(depth[inside], [2, 98]) if inside.any() else (depth.min(), depth.max())
        near = np.clip((hi - depth) / max(hi - lo, 1e-6), 0, 1)
        colored = cv2.applyColorMap((near * 255).astype(np.uint8), cv2.COLORMAP_TURBO)[..., ::-1] / 255
        gray = np.repeat((0.35 + 0.4 * np.clip((depth - depth.min()) / max(np.ptp(depth), 1e-6), 0, 1))[..., None], 3, 2)
        a = alpha[..., None]
        self.save('3_depth', to_image(self.around(colored * a + gray * (1 - a))))

    @staticmethod
    def normals(height):
        gy, gx = np.gradient(height)
        n = np.dstack([-gx, -gy, np.ones_like(height)])
        return n / np.linalg.norm(n, axis=2, keepdims=True)

    def height(self, maps):
        n = self.normals(maps['height'])
        light = np.array([-0.45, -0.55, 0.7]) / np.linalg.norm([-0.45, -0.55, 0.7])
        shade = np.clip(n @ light, 0, 1)
        top = maps['height'] / max(float(maps['height'].max()), 1e-6)
        value = (0.25 + 0.55 * shade + 0.2 * top)[..., None] * np.array([1.0, 0.97, 0.92])
        a = maps['alpha'][..., None]
        self.save('4_height', to_image(value * a + BACKGROUND * (1 - a)))

    def sticker(self, maps):
        n = self.normals(maps['height'])
        light = np.array([-0.45, -0.55, 0.7]) / np.linalg.norm([-0.45, -0.55, 0.7])
        half = (light + [0, 0, 1]) / np.linalg.norm(light + [0, 0, 1])
        diffuse = np.clip(n @ light, 0, 1)
        gloss = np.clip(n @ half, 0, 1) ** 70 * 0.75  # clearcoat-like highlight
        color = maps['color'] * (0.45 + 0.6 * diffuse[..., None]) + gloss[..., None]
        a = maps['alpha']
        h, w = a.shape
        r = max(2, round(max(h, w) * 0.012))
        shadow = cv2.GaussianBlur(np.roll(np.roll(a, r, 0), r, 1), (0, 0), r * 1.5) * 0.28
        ground = BACKGROUND * (1 - shadow[..., None])
        self.save('5_sticker', to_image(color * a[..., None] + ground * (1 - a[..., None])))

    def compose(self, height=360):
        tiles = []
        try:
            font = ImageFont.truetype(str(FONT), max(18, height // 12))
        except OSError:
            font = ImageFont.load_default()
        for name in self.stages:
            image = Image.open(self.folder / f'{name}.jpg')
            image = image.resize((max(1, round(image.width * height / image.height)), height), Image.Resampling.LANCZOS)
            label = round(ImageDraw.Draw(image).textlength(LABELS[name], font=font)) + 24
            # A narrow (portrait) stage gets side margins so its label fits.
            tile = Image.new('RGB', (max(image.width, label), height + height // 7), (255, 255, 255))
            tile.paste(image, ((tile.width - image.width) // 2, 0))
            ImageDraw.Draw(tile).text((12, height + height // 40), LABELS[name], fill=(41, 70, 83), font=font)
            tiles.append(tile)
        gap = 8
        strip = Image.new('RGB', (sum(t.width for t in tiles) + gap * (len(tiles) - 1), tiles[0].height), (213, 229, 237))
        x = 0
        for tile in tiles:
            strip.paste(tile, (x, 0))
            x += tile.width + gap
        strip.save(self.output / 'process.jpg', quality=88)
