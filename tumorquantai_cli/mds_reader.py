"""Read Motic MDS pixel pyramids without exporting private metadata.

Only ``DSI0`` tile streams are exposed. Label, macro, and acquisition streams
are deliberately inaccessible through this interface.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterator

import numpy as np
import olefile
from PIL import Image


class MdsReadError(RuntimeError):
    """Raised when a Motic MDS pixel pyramid cannot be read safely."""


@dataclass(frozen=True)
class MdsLevel:
    index: int
    name: str
    rows: int
    columns: int
    tile_width: int
    tile_height: int

    @property
    def width(self) -> int:
        return self.columns * self.tile_width

    @property
    def height(self) -> int:
        return self.rows * self.tile_height

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


def parse_tile_name(value: str) -> tuple[int, int] | None:
    parts = value.split("_")
    if len(parts) != 2:
        return None
    try:
        row, column = (int(part) for part in parts)
    except ValueError:
        return None
    if row < 0 or column < 0:
        return None
    return row, column


def level_sort_key(value: str) -> tuple[int, float | str]:
    try:
        return (0, -float(value))
    except ValueError:
        return (1, value.casefold())


def digest_file(path: Path) -> tuple[int, str]:
    """Hash one stable regular file and detect concurrent replacement."""
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise MdsReadError(f"Input is not a regular file: {candidate}")
    path = candidate.resolve()
    before = path.stat()
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    after = path.stat()
    identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if identity(before) != identity(after):
        raise MdsReadError(f"File changed while hashing: {path}")
    return size, digest.hexdigest()


class MdsPixels:
    """Small, read-only MDS pixel reader backed by :mod:`olefile`."""

    def __init__(self, path: Path) -> None:
        candidate = path.expanduser().absolute()
        if candidate.is_symlink() or not candidate.is_file():
            raise MdsReadError(f"MDS input is not a regular file: {candidate}")
        self.path = candidate.resolve()
        if self.path.suffix.casefold() != ".mds":
            raise MdsReadError(f"MDS input must end in .mds: {self.path}")
        try:
            self.ole = olefile.OleFileIO(str(self.path))
        except (OSError, IOError, olefile.OleFileError) as exc:
            raise MdsReadError(f"Cannot open MDS OLE structure: {self.path}") from exc
        self._tiles: dict[str, dict[tuple[int, int], tuple[str, ...]]] = {}
        try:
            self._levels = self._discover_levels()
        except Exception:
            self.ole.close()
            raise

    def __enter__(self) -> "MdsPixels":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.ole.close()

    @property
    def levels(self) -> tuple[MdsLevel, ...]:
        return self._levels

    def _discover_levels(self) -> tuple[MdsLevel, ...]:
        grouped: dict[str, dict[tuple[int, int], tuple[str, ...]]] = {}
        for stream in self.ole.listdir(streams=True, storages=False):
            if len(stream) != 3 or stream[0] != "DSI0":
                continue
            coordinate = parse_tile_name(stream[2])
            if coordinate is None:
                continue
            grouped.setdefault(stream[1], {})[coordinate] = tuple(stream)
        if not grouped:
            raise MdsReadError(f"MDS contains no DSI0 pixel tiles: {self.path}")

        levels: list[MdsLevel] = []
        for index, name in enumerate(sorted(grouped, key=level_sort_key)):
            tiles = grouped[name]
            first_path = tiles[min(tiles)]
            try:
                encoded = self.ole.openstream(list(first_path)).read()
                with Image.open(BytesIO(encoded)) as image:
                    tile_width, tile_height = image.size
            except Exception as exc:
                raise MdsReadError(
                    f"Cannot decode the first tile in MDS level {name!r}: "
                    f"{self.path}"
                ) from exc
            if tile_width <= 0 or tile_height <= 0:
                raise MdsReadError(f"Invalid tile dimensions in {self.path}")
            rows = max(row for row, _ in tiles) + 1
            columns = max(column for _, column in tiles) + 1
            self._tiles[name] = tiles
            levels.append(
                MdsLevel(
                    index=index,
                    name=name,
                    rows=rows,
                    columns=columns,
                    tile_width=tile_width,
                    tile_height=tile_height,
                )
            )
        return tuple(levels)

    def read_tile(
        self,
        level: MdsLevel,
        row: int,
        column: int,
        *,
        fill_value: int = 255,
    ) -> np.ndarray:
        """Decode one RGB tile, returning white for an absent grid position."""
        if level not in self._levels:
            raise MdsReadError("MDS level does not belong to this slide")
        if not 0 <= row < level.rows or not 0 <= column < level.columns:
            raise MdsReadError("MDS tile coordinate is outside the level grid")
        expected_shape = (level.tile_height, level.tile_width, 3)
        stream = self._tiles[level.name].get((row, column))
        if stream is None:
            return np.full(expected_shape, fill_value, dtype=np.uint8)
        try:
            encoded = self.ole.openstream(list(stream)).read()
            with Image.open(BytesIO(encoded)) as image:
                array = np.asarray(image.convert("RGB"), dtype=np.uint8)
        except Exception as exc:
            raise MdsReadError(
                f"Cannot decode tile {level.name}/{row}_{column} in {self.path}"
            ) from exc
        if array.shape == expected_shape:
            return np.ascontiguousarray(array)
        padded = np.full(expected_shape, fill_value, dtype=np.uint8)
        height = min(array.shape[0], level.tile_height)
        width = min(array.shape[1], level.tile_width)
        padded[:height, :width, :] = array[:height, :width, :3]
        return padded

    def iter_level_tiles(
        self, level: MdsLevel, fill_value: int = 255
    ) -> Iterator[np.ndarray]:
        for row in range(level.rows):
            for column in range(level.columns):
                yield self.read_tile(level, row, column, fill_value=fill_value)

    def iter_level_tiles_with_coordinates(
        self, level: MdsLevel, fill_value: int = 255
    ) -> Iterator[tuple[int, int, np.ndarray]]:
        for row in range(level.rows):
            for column in range(level.columns):
                yield (
                    row,
                    column,
                    self.read_tile(level, row, column, fill_value=fill_value),
                )

    def read_tile_block(
        self,
        level: MdsLevel,
        row_start: int,
        row_stop: int,
        column_start: int,
        column_stop: int,
        *,
        fill_value: int = 255,
    ) -> np.ndarray:
        """Decode a half-open rectangular group of MDS tiles."""
        if (
            not 0 <= row_start < row_stop <= level.rows
            or not 0 <= column_start < column_stop <= level.columns
        ):
            raise MdsReadError("MDS tile block is outside the level grid")
        result = np.full(
            (
                (row_stop - row_start) * level.tile_height,
                (column_stop - column_start) * level.tile_width,
                3,
            ),
            fill_value,
            dtype=np.uint8,
        )
        for row in range(row_start, row_stop):
            y0 = (row - row_start) * level.tile_height
            for column in range(column_start, column_stop):
                x0 = (column - column_start) * level.tile_width
                result[
                    y0 : y0 + level.tile_height,
                    x0 : x0 + level.tile_width,
                ] = self.read_tile(level, row, column, fill_value=fill_value)
        return result

    def read_level_array(
        self,
        level: MdsLevel,
        *,
        maximum_pixels: int = 64_000_000,
        fill_value: int = 255,
    ) -> np.ndarray:
        """Decode a bounded complete level for overview and registration use."""
        if level.pixel_count > maximum_pixels:
            raise MdsReadError(
                f"MDS level has {level.pixel_count:,} pixels; bounded overview "
                f"limit is {maximum_pixels:,}"
            )
        return self.read_tile_block(
            level,
            0,
            level.rows,
            0,
            level.columns,
            fill_value=fill_value,
        )
