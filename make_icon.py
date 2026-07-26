"""Generates static/apple-touch-icon.png — a simple, crisp icon that reads
well at small sizes: a dark ground with an ascending 3-bar chart glyph,
matching the app's palette. Run once locally: python3 make_icon.py
"""
from PIL import Image, ImageDraw

SIZE = 180
img = Image.new("RGB", (SIZE, SIZE), "#0b0e14")
draw = ImageDraw.Draw(img)

# subtle diagonal-ish gradient by drawing soft overlapping rectangles
top = (11, 14, 20)
bottom = (20, 28, 38)
for y in range(SIZE):
    t = y / SIZE
    r = int(top[0] + (bottom[0] - top[0]) * t)
    g = int(top[1] + (bottom[1] - top[1]) * t)
    b = int(top[2] + (bottom[2] - top[2]) * t)
    draw.line([(0, y), (SIZE, y)], fill=(r, g, b))

# three ascending bars, rounded tops, centered as a group
bar_w = 26
gap = 16
heights = [64, 96, 128]
colors = ["#5ec8c2", "#e3a857", "#e3a857"]
total_w = bar_w * 3 + gap * 2
start_x = (SIZE - total_w) // 2
base_y = 138

for i, h in enumerate(heights):
    x0 = start_x + i * (bar_w + gap)
    x1 = x0 + bar_w
    y1 = base_y
    y0 = base_y - h
    draw.rounded_rectangle([x0, y0, x1, y1], radius=7, fill=colors[i])

# thin baseline
draw.line([(34, base_y + 10), (SIZE - 34, base_y + 10)], fill="#232b3a", width=2)

img.save("static/apple-touch-icon.png")
print("Saved static/apple-touch-icon.png")
