# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import logging
from typing import List
from typing import Literal
from typing import Optional

from google.genai import types
from pydantic import ConfigDict

from ..tools.tool_configs import ToolConfig
from .base_agent_config import BaseAgentConfig
from .common_configs import CodeConfig

logger = logging.getLogger('google_adk.' + __name__)


class LlmAgentConfig(BaseAgentConfig):
  """The config for the YAML schema of a LlmAgent."""

  model_config = ConfigDict(
      extra='forbid',
  )

  agent_class: Literal['LlmAgent', ''] = 'LlmAgent'
  """The value is used to uniquely identify the LlmAgent class. If it is
  empty, it is by default an LlmAgent."""

  model: Optional[str] = None
  """Optional. LlmAgent.model. If not set, the model will be inherited from
  the ancestor."""

  instruction: str
  """Required. LlmAgent.instruction."""

  disallow_transfer_to_parent: Optional[bool] = None
  """Optional. LlmAgent.disallow_transfer_to_parent."""

  disallow_transfer_to_peers: Optional[bool] = None
  """Optional. LlmAgent.disallow_transfer_to_peers."""

  input_schema: Optional[CodeConfig] = None
  """Optional. LlmAgent.input_schema."""

  output_schema: Optional[CodeConfig] = None
  """Optional. LlmAgent.output_schema."""

  output_key: Optional[str] = None
  """Optional. LlmAgent.output_key."""

  include_contents: Literal['default', 'none'] = 'default'
  """Optional. LlmAgent.include_contents."""

  tools: Optional[list[ToolConfig]] = None
  """Optional. LlmAgent.tools.

  Examples:

    For ADK built-in tools in `google.adk.tools` package, they can be referenced
    directly with the name:

      ```
      tools:
        - name: google_search
        - name: load_memory
      ```

    For user-defined tools, they can be referenced with fully qualified name:

      ```
      tools:
        - name: my_library.my_tools.my_tool
      ```

    For tools that needs to be created via functions:

      ```
      tools:
        - name: my_library.my_tools.create_tool
          args:
            - name: param1
              value: value1
            - name: param2
              value: value2
      ```

    For more advanced tools, instead of specifying arguments in config, it's
    recommended to define them in Python files and reference them. E.g.,

      ```
      # tools.py
      my_mcp_toolset = MCPToolset(
          connection_params=StdioServerParameters(
              command="npx",
              args=["-y", "@notionhq/notion-mcp-server"],
              env={"OPENAPI_MCP_HEADERS": NOTION_HEADERS},
          )
      )
      ```

    Then, reference the toolset in config:

    ```
    tools:
      - name: tools.my_mcp_toolset
    ```
  """

  before_model_callbacks: Optional[List[CodeConfig]] = None
  """Optional. LlmAgent.before_model_callbacks.

  Example:

    ```
    before_model_callbacks:
      - name: my_library.callbacks.before_model_callback
    ```
  """

  after_model_callbacks: Optional[List[CodeConfig]] = None
  """Optional. LlmAgent.after_model_callbacks."""

  before_tool_callbacks: Optional[List[CodeConfig]] = None
  """Optional. LlmAgent.before_tool_callbacks."""

  after_tool_callbacks: Optional[List[CodeConfig]] = None
  """Optional. LlmAgent.after_tool_callbacks."""

  generate_content_config: Optional[types.GenerateContentConfig] = None
  """Optional. LlmAgent.generate_content_config."""
