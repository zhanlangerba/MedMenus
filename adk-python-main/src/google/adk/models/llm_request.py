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

from collections.abc import AsyncGenerator as ABCAsyncGenerator
import inspect
from typing import get_origin
from typing import Optional

from google.genai import types
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..tools.base_tool import BaseTool
from ..tools.function_tool import FunctionTool


def _find_tool_with_function_declarations(
    llm_request: LlmRequest,
) -> Optional[types.Tool]:
  """Find an existing Tool with function_declarations in the LlmRequest."""
  # TODO: add individual tool with declaration and merge in google_llm.py
  if not llm_request.config or not llm_request.config.tools:
    return None

  return next(
      (
          tool
          for tool in llm_request.config.tools
          if isinstance(tool, types.Tool) and tool.function_declarations
      ),
      None,
  )


class LlmRequest(BaseModel):
  """LLM request class that allows passing in tools, output schema and system

  instructions to the model.

  Attributes:
    model: The model name.
    contents: The contents to send to the model.
    config: Additional config for the generate content request.
    tools_dict: The tools dictionary.
  """

  model_config = ConfigDict(arbitrary_types_allowed=True)
  """The pydantic model config."""

  model: Optional[str] = None
  """The model name."""

  contents: list[types.Content] = Field(default_factory=list)
  """The contents to send to the model."""

  config: types.GenerateContentConfig = Field(
      default_factory=types.GenerateContentConfig
  )
  """Additional config for the generate content request.

  tools in generate_content_config should not be set.
  """
  live_connect_config: Optional[types.LiveConnectConfig] = None
  """Live connection config.
  """
  tools_dict: dict[str, BaseTool] = Field(default_factory=dict, exclude=True)
  """The tools dictionary."""

  def append_instructions(self, instructions: list[str]) -> None:
    """Appends instructions to the system instruction.

    Args:
      instructions: The instructions to append.
    """

    if self.config.system_instruction:
      self.config.system_instruction += '\n\n' + '\n\n'.join(instructions)
    else:
      self.config.system_instruction = '\n\n'.join(instructions)

  def append_tools(self, tools: list[BaseTool]) -> None:
    """Appends tools to the request.

    Args:
      tools: The tools to append.
    """

    if not tools:
      return
    declarations = []
    for tool in tools:
      if self.live_connect_config is not None:
        # ignore response for tools that returns AsyncGenerator that the model
        # can't understand yet even though the model can't handle it, streaming
        # tools can handle it.
        # to check type, use typing.collections.abc.AsyncGenerator and not
        # typing.AsyncGenerator
        is_async_generator_return = False
        if isinstance(tool, FunctionTool):
          signature = inspect.signature(tool.func)
          is_async_generator_return = (
              get_origin(signature.return_annotation) is ABCAsyncGenerator
          )
        declaration = tool._get_declaration(
            ignore_return_declaration=is_async_generator_return
        )
      else:
        declaration = tool._get_declaration()
      if declaration:
        declarations.append(declaration)
        self.tools_dict[tool.name] = tool
    if declarations:
      if self.config.tools is None:
        self.config.tools = []

      # Find existing tool with function_declarations and append to it
      if tool_with_function_declarations := _find_tool_with_function_declarations(
          self
      ):
        if tool_with_function_declarations.function_declarations is None:
          tool_with_function_declarations.function_declarations = []
        tool_with_function_declarations.function_declarations.extend(
            declarations
        )
      else:
        # No existing tool with function_declarations, create new one
        self.config.tools.append(types.Tool(function_declarations=declarations))

  def set_output_schema(self, base_model: type[BaseModel]) -> None:
    """Sets the output schema for the request.

    Args:
      base_model: The pydantic base model to set the output schema to.
    """

    self.config.response_schema = base_model
    self.config.response_mime_type = 'application/json'
