
import os
import json
import google.generativeai as genai
from aisuite.provider import Provider, LLMError
from aisuite.framework import ChatCompletionResponse

class GeminiProvider(Provider):
    def __init__(self, **config):
        self.api_key = config.get("api_key") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
             raise LLMError("Missing GOOGLE_API_KEY")
        genai.configure(api_key=self.api_key)

    def chat_completions_create(self, model, messages, **kwargs):
        model_name = model
        
        # Tools
        tools_schema = kwargs.get("tools")
        genai_tools = None
        if tools_schema:
            funcs = []
            for t in tools_schema:
                if t.get("type") == "function":
                    funcs.append(t["function"])
            if funcs:
                genai_tools = {"function_declarations": funcs}

        model_params = {}
        if genai_tools:
            model_params['tools'] = genai_tools

        # System instruction
        system_instruction = None
        if "system_instruction" in kwargs:
             system_instruction = kwargs["system_instruction"]
        
        chat_history = []
        
        for msg in messages:
            if hasattr(msg, "get"):
                 role = msg.get("role")
                 content = msg.get("content")
                 tool_calls = msg.get("tool_calls")
                 tool_name = msg.get("name")
            else:
                 role = getattr(msg, "role", None)
                 content = getattr(msg, "content", None)
                 tool_calls = getattr(msg, "tool_calls", None)
                 tool_name = getattr(msg, "name", None)

            if role == "system":
                system_instruction = content
            elif role == "user":
                chat_history.append({"role": "user", "parts": [content]})
            elif role == "assistant":
                if tool_calls:
                    parts = []
                    for tc in tool_calls:
                        # tool_calls might be list of dicts or objects
                        if hasattr(tc, "function"):
                             # Object (ToolCall)
                             fn = tc.function
                             fn_name = fn.name
                             fn_args = fn.arguments
                        else:
                             # Dict
                             fn = tc["function"]
                             fn_name = fn["name"]
                             fn_args = fn["arguments"]

                        if isinstance(fn_args, str):
                             fn_args_dict = json.loads(fn_args)
                        else:
                             fn_args_dict = fn_args

                        parts.append({
                            "function_call": {
                                "name": fn_name,
                                "args": fn_args_dict
                            }
                        })
                    chat_history.append({"role": "model", "parts": parts})
                else:
                    if content:
                         chat_history.append({"role": "model", "parts": [content]})
            elif role == "tool":
                # Tool response
                try:
                    if isinstance(content, str):
                        resp_dict = json.loads(content)
                    else:
                        resp_dict = content
                except:
                    resp_dict = {"result": str(content)}
                
                if not isinstance(resp_dict, dict):
                    resp_dict = {"result": resp_dict}
                
                chat_history.append({
                    "role": "function",
                    "parts": [{
                        "function_response": {
                            "name": tool_name,
                            "response": resp_dict
                        }
                    }]
                })

        if system_instruction:
            model_params["system_instruction"] = system_instruction

        genai_model = genai.GenerativeModel(model_name, **model_params)
        
        response = genai_model.generate_content(chat_history)
        
        # Convert response
        resp = ChatCompletionResponse()
        
        if not response.candidates:
            resp.choices[0].message.content = "I cannot provide a response due to safety settings."
            resp.choices[0].finish_reason = "stop"
            return resp

        candidate = response.candidates[0]
        tool_calls = []
        text_content = ""
        
        for part in candidate.content.parts:
            if part.function_call:
                fc = part.function_call
                call_id = f"call_{fc.name}_{os.urandom(4).hex()}"
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(dict(fc.args))
                    }
                })
            if part.text:
                text_content += part.text
        
        if tool_calls:
            resp.choices[0].message.tool_calls = tool_calls
            resp.choices[0].finish_reason = "tool_calls"
            resp.choices[0].message.content = None 
        else:
            resp.choices[0].message.content = text_content
            resp.choices[0].finish_reason = "stop"
            
        return resp
