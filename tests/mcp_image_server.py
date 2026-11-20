# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tiny MCP stdio server with image tools, launched by the MCP backend tests."""

import base64
import io

from mcp.server.fastmcp import FastMCP, Image as MCPImage
from PIL import Image, ImageDraw

mcp = FastMCP("mock-image")


@mcp.tool()
def generate_image(prompt: str, width: int = 512, height: int = 288) -> MCPImage:
    """Returns an ImageContent result (the common MCP image shape)."""
    img = Image.new("RGB", (int(width), int(height)), "white")
    ImageDraw.Draw(img).text((10, 10), prompt[:40], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return MCPImage(data=buf.getvalue(), format="png")


@mcp.tool()
def generate_image_url(prompt: str) -> str:
    """Returns a data URL as plain text (servers that answer with text/URLs)."""
    img = Image.new("RGB", (64, 64), "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


if __name__ == "__main__":
    mcp.run()
