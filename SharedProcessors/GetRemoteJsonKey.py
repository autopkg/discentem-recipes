from autopkglib import Processor, ProcessorError, URLGetter
import hashlib
import json

__all__ = ["GetRemoteJsonKey"]

class GetRemoteJsonKey(URLGetter):
    input_variables = {
        "url": {
            "required": True,
            "description": "URL to fetch JSON from"
        },
        "key": {
            "required": True,
            "description": "Key to extract from JSON"
        },
        "output_variable": {
            "required": True,
            "description": "Name of the output variable to store extracted value"
        }
    }

    output_variables = {
        # result_variable will be set dynamically based on input
        "get_remote_json_key_summary_result": {
            "description": "Summary of the JSON key extraction process"
        }
    }

    def main(self):
        data = self.download(self.env["url"])
        url = self.env["url"]
        key = self.env.get("key")
        output_variable = self.env.get("output_variable")
        if not output_variable:
            raise ProcessorError("The 'output_variable' input variable is required.")
        if not url or not key:
            raise ProcessorError("Both 'url' and 'key' input variables are required.")
        self.output(f"Fetching JSON from URL: {url}")

        try:
            jdata = json.loads(data)
            extracted_value = jdata.get(key, None)
            self.env[output_variable] = extracted_value
            self.output(f"{output_variable}: {extracted_value}")
        except Exception as e:
            raise ProcessorError(f"Failed to extract key from JSON: {e}")   
        
        self.output(f"Extracted value for '{key}': {extracted_value}")
        self.env["get_remote_json_key_summary_result"] = {
                "summary_text": "The following new items were downloaded:",
                "data": {"downloaded_json": url},
            }

if __name__ == "__main__":
    PROCESSOR = GetRemoteJsonKey()
    PROCESSOR.execute_shell()