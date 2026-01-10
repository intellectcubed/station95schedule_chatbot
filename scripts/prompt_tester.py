#!/usr/bin/env python3
"""
LLM Prompt Tester

A utility to test LLM prompts by reading from a file, merging placeholder values,
and sending to ChatGPT models with optional tool binding.

Usage:
    python prompt_tester.py <prompt_file> [options]

Examples:
    # Basic usage with gpt-4o-mini (default)
    python prompt_tester.py ai_prompts/system_prompt.md

    # Use gpt-4o instead
    python prompt_tester.py ai_prompts/system_prompt.md --model gpt-4o

    # Adjust temperature
    python prompt_tester.py ai_prompts/system_prompt.md --temperature 0.7

    # Provide placeholder values
    python prompt_tester.py ai_prompts/IntentDetectionPrompt.md \
        --placeholders "message=We need coverage tonight" \
        --placeholders "current_date=2026-01-03"

    # Load JSON from file using @ prefix
    python prompt_tester.py ai_prompts/system_prompt.md \
        -p "schedule_state=@data/schedule_saturday.json"

    # Enable tool binding (allows LLM to call functions)
    python prompt_tester.py ai_prompts/system_prompt.md --tools --verbose
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage


class PromptTester:
    """
    A utility class for testing LLM prompts.

    Reads prompts from files, merges placeholder values, and sends to ChatGPT models.
    Optionally supports tool binding for function calling.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        enable_tools: bool = False
    ):
        """
        Initialize the prompt tester.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o-mini)
            temperature: Temperature setting (default: 0.3)
            enable_tools: If True, bind tools to the LLM for function calling
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.model = model
        self.temperature = temperature
        self.enable_tools = enable_tools
        self.llm = None
        self.tools = []

        # Load tools if enabled
        if self.enable_tools:
            self._load_tools()

    def _load_tools(self):
        """Load tools from src.tools module."""
        try:
            # Add parent directory to path to import src module
            parent_dir = Path(__file__).parent.parent
            sys.path.insert(0, str(parent_dir))

            from src.tools import all_tools
            self.tools = all_tools

            if self.tools:
                tool_names = [tool.name for tool in self.tools]
                print(f"✅ Loaded {len(self.tools)} tools: {', '.join(tool_names)}")
            else:
                print("⚠️  No tools found in src.tools.all_tools")

        except ImportError as e:
            print(f"❌ Failed to import tools: {e}")
            print("   Tools will not be available. Make sure src/tools.py exists.")
            self.tools = []

    def _create_llm(self) -> ChatOpenAI:
        """Create and return ChatOpenAI instance, optionally with tools bound."""
        if self.llm is None:
            llm = ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                api_key=self.api_key
            )

            # Bind tools if enabled and available
            if self.enable_tools and self.tools:
                self.llm = llm.bind_tools(self.tools)
            else:
                self.llm = llm

        return self.llm

    def read_prompt(self, prompt_file: str | Path) -> str:
        """
        Read prompt content from file.

        Args:
            prompt_file: Path to prompt file

        Returns:
            Prompt content as string

        Raises:
            FileNotFoundError: If prompt file doesn't exist
        """
        prompt_path = Path(prompt_file)

        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        return prompt_path.read_text()

    def merge_placeholders(
        self,
        prompt_template: str,
        placeholders: Dict[str, Any]
    ) -> str:
        """
        Merge placeholder values into prompt template.

        Handles both string and JSON values. Non-string values (dicts, lists)
        are automatically serialized to JSON.

        Args:
            prompt_template: Template string with {placeholder} syntax
            placeholders: Dictionary of placeholder values

        Returns:
            Prompt with placeholders filled in
        """
        # Convert non-string values to JSON strings
        formatted_placeholders = {}
        for key, value in placeholders.items():
            if isinstance(value, (dict, list)):
                # Serialize JSON objects/arrays to formatted strings
                formatted_placeholders[key] = json.dumps(value, indent=2)
            else:
                formatted_placeholders[key] = value

        try:
            return prompt_template.format(**formatted_placeholders)
        except KeyError as e:
            raise ValueError(
                f"Missing placeholder value: {e}. "
                f"Available placeholders: {list(placeholders.keys())}"
            )

    def _execute_tool_call(self, tool_call: dict, verbose: bool = False) -> Any:
        """
        Execute a tool call and return the result.

        Args:
            tool_call: Tool call dictionary with 'name' and 'args'
            verbose: If True, print detailed information

        Returns:
            Tool execution result
        """
        tool_name = tool_call.get('name')
        tool_args = tool_call.get('args', {})

        if verbose:
            print(f"\n🔧 TOOL CALL: {tool_name}")
            print(f"   Arguments: {json.dumps(tool_args, indent=2)}")

        # Find the tool by name
        tool_func = None
        for tool in self.tools:
            if tool.name == tool_name:
                tool_func = tool
                break

        if tool_func is None:
            error_msg = f"Tool '{tool_name}' not found"
            if verbose:
                print(f"   ❌ {error_msg}")
            return {"error": error_msg}

        # Execute the tool
        try:
            result = tool_func.invoke(tool_args)
            if verbose:
                print(f"   ✅ Result: {result}")
            return result
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            if verbose:
                print(f"   ❌ {error_msg}")
            return {"error": error_msg}

    def send_prompt(
        self,
        prompt: str,
        verbose: bool = False,
        max_iterations: int = 5
    ) -> Dict[str, Any]:
        """
        Send prompt to ChatGPT and get response.

        If tools are enabled, handles tool calls in a loop until the LLM
        returns a final text response.

        Args:
            prompt: The prompt to send
            verbose: If True, print detailed information
            max_iterations: Maximum number of tool call iterations (default: 5)

        Returns:
            Dictionary with response content, model info, usage stats, and tool calls
        """
        llm = self._create_llm()

        if verbose:
            print(f"\n{'='*80}")
            print(f"MODEL: {self.model}")
            print(f"TEMPERATURE: {self.temperature}")
            print(f"TOOLS: {'Enabled' if self.enable_tools and self.tools else 'Disabled'}")
            print(f"{'='*80}")
            print(f"\nPROMPT:\n{prompt}\n")
            print(f"{'-'*80}")

        # Initialize conversation with the prompt
        messages = [HumanMessage(content=prompt)]

        all_tool_calls = []
        total_usage = {}
        iteration = 0

        # Tool execution loop
        while iteration < max_iterations:
            iteration += 1

            # Send messages to LLM
            response = llm.invoke(messages)

            # Accumulate token usage (only numeric values)
            if hasattr(response, 'response_metadata'):
                usage = response.response_metadata.get('token_usage', {})
                for key, value in usage.items():
                    # Only accumulate numeric values (skip nested dicts)
                    if isinstance(value, (int, float)):
                        total_usage[key] = total_usage.get(key, 0) + value
                    elif key not in total_usage:
                        # For non-numeric values, just store the first occurrence
                        total_usage[key] = value

            # Check if LLM wants to call tools
            if hasattr(response, 'tool_calls') and response.tool_calls:
                if verbose:
                    print(f"\n{'='*80}")
                    print(f"ITERATION {iteration}: LLM requested {len(response.tool_calls)} tool call(s)")
                    print(f"{'='*80}")

                # Add AI message with tool calls to conversation
                messages.append(response)

                # Execute each tool call
                for tool_call in response.tool_calls:
                    all_tool_calls.append(tool_call)

                    # Execute the tool
                    result = self._execute_tool_call(tool_call, verbose=verbose)

                    # Add tool result to conversation
                    tool_message = ToolMessage(
                        content=json.dumps(result),
                        tool_call_id=tool_call.get('id', 'unknown')
                    )
                    messages.append(tool_message)

                # Continue loop to get LLM's next response
                continue

            else:
                # No tool calls - this is the final response
                content = response.content if hasattr(response, 'content') else str(response)

                if verbose:
                    print(f"\n{'='*80}")
                    print(f"FINAL RESPONSE (after {iteration} iteration(s)):")
                    print(f"{'='*80}")
                    print(f"\n{content}\n")
                    if total_usage:
                        print(f"{'-'*80}")
                        print(f"TOTAL TOKENS: {total_usage.get('total_tokens', 'N/A')} "
                              f"(prompt: {total_usage.get('prompt_tokens', 'N/A')}, "
                              f"completion: {total_usage.get('completion_tokens', 'N/A')})")
                    print(f"{'='*80}\n")

                return {
                    'model': self.model,
                    'temperature': self.temperature,
                    'content': content,
                    'usage': total_usage,
                    'tool_calls': all_tool_calls,
                    'iterations': iteration
                }

        # Max iterations reached
        error_msg = f"Max iterations ({max_iterations}) reached without final response"
        if verbose:
            print(f"\n⚠️  {error_msg}")

        return {
            'model': self.model,
            'temperature': self.temperature,
            'content': error_msg,
            'usage': total_usage,
            'tool_calls': all_tool_calls,
            'iterations': iteration,
            'error': 'max_iterations_reached'
        }

    def test_prompt(
        self,
        prompt_file: str | Path,
        placeholders: Dict[str, Any] | None = None,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Complete workflow: read, merge, and send prompt.

        Args:
            prompt_file: Path to prompt file
            placeholders: Dictionary of placeholder values (optional)
            verbose: If True, print detailed information

        Returns:
            Dictionary with response content, model info, usage stats, and tool calls
        """
        # Read prompt
        prompt_template = self.read_prompt(prompt_file)

        # Merge placeholders if provided
        if placeholders:
            prompt = self.merge_placeholders(prompt_template, placeholders)
        else:
            prompt = prompt_template

        # Send to LLM
        return self.send_prompt(prompt, verbose=verbose)


def parse_placeholders(placeholder_args: list[str]) -> Dict[str, Any]:
    """
    Parse placeholder arguments into dictionary.

    Supports loading JSON from files using '@' prefix:
        -p "schedule_state=@schedule.json"

    Args:
        placeholder_args: List of "key=value" strings

    Returns:
        Dictionary of placeholder key-value pairs
    """
    placeholders = {}

    for arg in placeholder_args:
        if '=' not in arg:
            raise ValueError(f"Invalid placeholder format: {arg}. Expected 'key=value'")

        key, value = arg.split('=', 1)
        key = key.strip()
        value = value.strip()

        # Check if value is a file reference (starts with @)
        if value.startswith("@"):
            file_path = value[1:]  # Remove '@' prefix
            try:
                with open(file_path) as f:
                    data = json.load(f)
                    placeholders[key] = data
                    print(f"✅ Loaded JSON from {file_path} for placeholder '{key}'")
            except FileNotFoundError:
                raise FileNotFoundError(f"File not found: {file_path} (for placeholder '{key}')")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in {file_path}: {e}")
        else:
            placeholders[key] = value

    return placeholders


def main():
    """Command-line interface for prompt tester."""
    parser = argparse.ArgumentParser(
        description="Test LLM prompts by reading from file and sending to ChatGPT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with default model (gpt-4o-mini)
  %(prog)s ai_prompts/system_prompt.md

  # Use gpt-4o
  %(prog)s ai_prompts/system_prompt.md --model gpt-4o

  # Adjust temperature
  %(prog)s ai_prompts/system_prompt.md --temperature 0.7

  # Provide placeholder values
  %(prog)s ai_prompts/IntentDetectionPrompt.md \\
      -p "message=We need coverage tonight" \\
      -p "current_date=2026-01-03" \\
      -p "current_time=21:08:00"

  # Load JSON from file using @ prefix
  %(prog)s ai_prompts/system_prompt.md \\
      -p "schedule_state=@data/schedule_saturday.json" \\
      -p "user_message=We can't make it tonight"

  # Enable tool binding (allows LLM to call functions)
  %(prog)s ai_prompts/system_prompt.md --tools --verbose

  # Output as JSON
  %(prog)s ai_prompts/system_prompt.md --json
        """
    )

    parser.add_argument(
        'prompt_file',
        help='Path to prompt file'
    )

    parser.add_argument(
        '-m', '--model',
        default='gpt-4o-mini',
        help='Model to use (default: gpt-4o-mini)'
    )

    parser.add_argument(
        '-t', '--temperature',
        type=float,
        default=0.3,
        help='Temperature setting (default: 0.3)'
    )

    parser.add_argument(
        '-p', '--placeholders',
        action='append',
        default=[],
        help='Placeholder values in key=value format. Use @filename to load JSON from file (e.g., -p "data=@file.json")'
    )

    parser.add_argument(
        '--tools',
        action='store_true',
        help='Enable tool binding (allows LLM to call functions from src/tools.py)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print detailed information'
    )

    parser.add_argument(
        '-j', '--json',
        action='store_true',
        help='Output result as JSON'
    )

    args = parser.parse_args()

    # try:
    #     # Parse placeholders
    #     placeholders = parse_placeholders(args.placeholders) if args.placeholders else None

    #     # Create tester
    #     tester = PromptTester(
    #         model=args.model,
    #         temperature=args.temperature,
    #         enable_tools=args.tools
    #     )

    #     # Test prompt
    #     result = tester.test_prompt(
    #         prompt_file=args.prompt_file,
    #         placeholders=placeholders,
    #         verbose=args.verbose or not args.json
    #     )

    #     # Output result
    #     if args.json:
    #         print(json.dumps(result, indent=2))
    #     elif not args.verbose:
    #         # If not verbose and not JSON, just print the response content
    #         print(result['content'])

    # except Exception as e:
    #     print(f"Error: {e}", file=sys.stderr)
    #     import traceback
    #     traceback.print_exc()
    #     sys.exit(1)
    for ctr in range(2):
        try:
            # Parse placeholders
            placeholders = parse_placeholders(args.placeholders) if args.placeholders else None

            if ctr == 0:
                model = 'gpt-4o-mini'
            else:
                model = 'gpt-4o'

            # Create tester
            tester = PromptTester(
                model=model,
                temperature=args.temperature,
                enable_tools=args.tools
            )

            # Test prompt
            result = tester.test_prompt(
                prompt_file=args.prompt_file,
                placeholders=placeholders,
                verbose=args.verbose or not args.json
            )

            # Output result
            if args.json:
                print(json.dumps(result, indent=2))
            elif not args.verbose:
                # If not verbose and not JSON, just print the response content
                print(result['content'])

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

"""
Example invocation: 

python scripts/prompt_tester.py ai_prompts/system_prompt.md \
      --model gpt-4o \
      --tools \
      --verbose \
      -p "user_message=42 has a crew from 1 - 4am" \
      -p "current_datetime=2026-01-03 21:08:00" \
      -p "sender_name=Kohler" \
      -p "sender_squad=42" \
      -p "current_datetime=2026-01-03 22:33:52" \
      -p "sender_role=Chief" \
      -p "resolved_days=2026-01-03" \
      -p "schedule_state=@data/schedule_saturday.json"

"""

if __name__ == '__main__':
    main()
