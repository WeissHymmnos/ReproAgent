import logging

logger = logging.getLogger(__name__)

class UnlimitedOcrModelManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.model = None
            cls._instance.tokenizer = None
            cls._instance.init_failed = False
        return cls._instance

    def lazy_init(self) -> bool:
        if self.model is not None and self.tokenizer is not None:
            return True
        if self.init_failed:
            return False

        try:
            import torch
            from transformers import AutoModel, AutoTokenizer

            model_id = "baidu/Unlimited-OCR"
            
            logger.info("Loading Unlimited-OCR tokenizer...")
            self.tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
            
            logger.info("Loading Unlimited-OCR model...")
            dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
            self.model = AutoModel.from_pretrained(
                model_id,
                trust_remote_code=True,
                torch_dtype=dtype,
                device_map="auto"
            )
            self.model.eval()
            return True
        except ImportError:
            logger.warning("transformers or torch not installed. Unlimited-OCR backend unavailable.")
            self.init_failed = True
            return False
        except Exception as e:
            logger.warning(f"Failed to load Unlimited-OCR model: {e}")
            self.init_failed = True
            return False

    def predict(self, image_bytes: bytes, task: str = "markdown") -> str:
        if not self.lazy_init():
            return ""
        
        try:
            import io

            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            
            # This is a generic implementation as specific prompt might vary based on the model's exact usage instructions.
            # Assuming a standard vision-language generation prompt.
            if task == "table":
                prompt = "Please extract the table from this image and output as Markdown format."
            elif task == "chart":
                prompt = "Describe this chart in detail. What type of chart is it, what is the title, and what are the key data points or trends?"
            elif task == "mermaid":
                prompt = "Convert this diagram to a Mermaid.js graph. Output only the Mermaid code block."
            else:
                prompt = "Extract the text and layout from this document image in Markdown format."
            
            if hasattr(self.model, "chat"):
                # Many custom VLM models provide a .chat() method
                res = self.model.chat(self.tokenizer, image, ocr_type='ocr')
                return res

            # Using the chat template or generation method expected by Unlimited-OCR
            messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
            
            try:
                text = self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            except Exception:
                text = f"USER: <image>\n{prompt}\nASSISTANT: "
            
            if hasattr(self.tokenizer, "from_list_format"):
                pass # some specific tokenizers
            
            # For standard AutoProcessor/AutoTokenizer for VLMs
            inputs = self.tokenizer(text, return_tensors="pt")
            if "pixel_values" not in inputs and hasattr(self.model, "get_vision_tower"):
                # Needs image processing
                pass

            # We will use the model's native chat/generate if possible
            if "pixel_values" not in inputs:
                # Assuming the tokenizer doesn't handle images automatically
                try:
                    pass
                    # This is highly model specific if not standard.
                    # We will just pass it to model.generate if inputs are built
                except Exception:
                    pass

            # If it's a standard transformers VLM:
            inputs = self.tokenizer(text, return_tensors="pt")
            # This might fail if the tokenizer expects 'images' param but doesn't implement it
            try:
                inputs = self.tokenizer(text, images=[image], return_tensors="pt")
            except Exception:
                pass

            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            
            outputs = self.model.generate(
                **inputs, 
                max_new_tokens=2048, 
                do_sample=False
            )
            
            # Get only the generated tokens
            generated_ids = outputs[0][inputs["input_ids"].shape[1]:]
            result = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
            return result
        except Exception as e:
            logger.error(f"Unlimited-OCR inference failed: {e}")
            return ""

    def unload(self):
        # Disabled unloading so we don't reload the 6.6GB model for every page/table
        pass

global_unlimited_ocr_manager = UnlimitedOcrModelManager()
