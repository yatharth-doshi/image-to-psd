import os
import secrets
import numpy as np
from colorthief import ColorThief
from sklearn.cluster import MeanShift
from PIL import Image, ImageDraw
from colormath.color_objects import LabColor, sRGBColor
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000
from wand.image import Image as WandImage
import urllib.request
# from .color_printer import *
from urllib.parse import urlparse

def patch_asscalar(a):
    return a.item()
setattr(np, "asscalar", patch_asscalar)

# Predefined color list
colour_list = [
    (255, 0, 0),    # Red
    (0, 255, 0),    # Green
    (0, 0, 255),    # Blue
    (255, 255, 0),  # Yellow
    (0, 255, 255),  # Cyan
    (255, 0, 255),  # Magenta
    (0, 0, 0),      # Black
    (255, 255, 255),# White
    (255, 165, 0),  # Orange
    (128, 0, 128),  # Purple
    (255, 192, 203),# Pink
    (165, 42, 42),  # Brown
    (128, 128, 128),# Gray
    (211, 211, 211),# Light Gray
    (169, 169, 169),# Dark Gray
    (128, 0, 0),    # Maroon
    (0, 0, 128),    # Navy
    (128, 128, 0),  # Olive
    (0, 128, 128),  # Teal
    (0, 255, 255),  # Aqua
    (0, 255, 0),    # Lime
    (255, 0, 255),  # Fuchsia
    (192, 192, 192),# Silver
    (255, 215, 0),  # Gold
    (75, 0, 130),   # Indigo
    (250, 128, 114),# Salmon
    (135, 206, 235),# Sky Blue
    (230, 230, 250),# Lavender
    (64, 224, 208), # Turquoise
    (34, 139, 34),  # Forest Green 
    (252, 236, 138),# Sweet Corn
    (242, 74, 95),  # Carnation
]

def get_token():
    return secrets.token_hex(32)

def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*rgb)

def get_dominant_colors(image_path, num_colors):
    color_thief = ColorThief(image_path)
    palette = color_thief.get_palette(color_count=num_colors)
    return palette

def lab_distance(color1, color2):
    lab1 = convert_color(sRGBColor(*color1, is_upscaled=True), LabColor)
    lab2 = convert_color(sRGBColor(*color2, is_upscaled=True), LabColor)
    return delta_e_cie2000(lab1, lab2)

def nearest_color(target_color, color_list):
    min_distance = float('inf')
    nearest = None
    for color in color_list:
        distance = lab_distance(target_color, color)
        if distance < min_distance:
            min_distance = distance
            nearest = color
    return nearest

def create_empty_background(image_shape, color_list):
    height, width, _ = image_shape
    background = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(background)
    num_colors = len(color_list)
    for i, color in enumerate(color_list):
        start_pos = (0, i * height // num_colors)
        end_pos = (width, (i + 1) * height // num_colors)
        draw.rectangle([start_pos, end_pos], fill=color)
    return np.array(background)


def process_image_layers(image_rgb, color_list, bandwidth):
    x = image_rgb.reshape(-1, 3)
    
    mean_shift = MeanShift(bandwidth=bandwidth, bin_seeding=True)
    labels = mean_shift.fit_predict(x)

    unique_labels = np.unique(labels)
    cluster_centers = np.array([np.mean(x[labels == label], axis=0) for label in unique_labels], dtype=int)

    layer_dict = {rgb_to_hex(color): [] for color in color_list}
    for index, pixel_color in enumerate(cluster_centers):
        pixel_color = tuple(map(int, pixel_color))
        nearest = nearest_color(pixel_color, color_list)
        layer_dict[rgb_to_hex(nearest)].append(index)

    merged_layers = [create_empty_background(image_rgb.shape, color_list)]
    for color_hex, indices in layer_dict.items():
        merged_layer = np.zeros_like(image_rgb, dtype=np.uint8)
        for index in indices:
            cluster_mask = labels == index
            cluster_mask_reshaped = cluster_mask.reshape(image_rgb.shape[0], image_rgb.shape[1])
            merged_layer[cluster_mask_reshaped] = image_rgb[cluster_mask_reshaped]
        alpha = np.where(merged_layer.sum(axis=2) > 0, 255, 0).astype(np.uint8)
        merged_layer = np.dstack((merged_layer, alpha))
        if np.any(merged_layer != 0):
            merged_layers.append(merged_layer)

    return merged_layers

def save_layers_as_psd(layers, output_path, save_individual_layers=False, dpi=300):
    try:
        with WandImage() as psd:
            for i, layer in enumerate(layers):
                img = Image.fromarray(layer, 'RGBA')
                img_path = f"{get_token()}.png"
                img.save(img_path)
                print(f"Saved image {img_path}")

                if not os.path.exists(img_path):
                    print(f"Image {img_path} does not exist")
                    continue

                with WandImage(filename=img_path) as img_wand:
                    img_wand.resolution = (dpi, dpi)
                    psd.sequence.append(img_wand)
                    print(f"Appended image {img_path} to PSD sequence")

                if save_individual_layers:
                    layer_name = f"Layer_{i}.png"
                    individual_layer_path = os.path.join('static/temp', f"{layer_name}")
                    img.save(individual_layer_path)
                    print(f"Saved individual layer to {individual_layer_path}")

                os.remove(img_path)

            psd.format = 'psd'
            psd.save(filename=output_path)
            print(f"Saved PSD to {output_path}")

        return output_path

    except Exception as e:
        print(f"An error occurred: {e}")
        raise


def process_image(image_path, method_type, bandwidth, is_dynamic, num_colors, save_layers=False):
    """
    - `image_path` (str): URL or local path to the image file.
    - `method_type` (int): Method type for processing (0 for default, 1 for custom).
    - `bandwidth` (int): Bandwidth parameter for MeanShift clustering (used if `method_type` is 1).
    - `is_dynamic` (int): Flag to use dynamic color extraction (1 for dynamic, 0 for predefined).
    - `num_colors` (int): Number of dominant colors to extract (used if `is_dynamic` is 1).
    - `save_layers` (bool): Flag to save individual layers as separate PNG files (default is False).
    """
    os.makedirs("psd_files", exist_ok=True)
    os.makedirs("static/temp", exist_ok=True)
    out_path = f"psd_files/{get_token()}.psd"

    # Check if the image_path is a URL or a local file path
    parsed_url = urlparse(image_path)
    if parsed_url.scheme in ('http', 'https'):
        img_path, _ = urllib.request.urlretrieve(image_path)
    else:
        img_path = image_path

    image = Image.open(img_path).convert('RGB')
    image_rgb = np.array(image)

    if is_dynamic == 1:
        dominant_colors_rgb = get_dominant_colors(img_path, num_colors)
        color_list = [tuple(color) for color in dominant_colors_rgb]
    else:
        color_list = colour_list

    if method_type == 0:
        layer_paths = process_image_layers(image_rgb, color_list, 25)
    elif method_type == 1:
        layer_paths = process_image_layers(image_rgb, color_list, bandwidth)

    return save_layers_as_psd(layer_paths, out_path, save_individual_layers=save_layers)
