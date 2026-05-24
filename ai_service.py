import os
import requests
import base64

class FarmAI:
    def __init__(self):
        # We will look for GEMINI_API_KEY in environment variables
        self.api_key = os.environ.get('GEMINI_API_KEY')
        # Using Gemini 1.5 Flash for speed and multimodal capabilities (Text + Images)
        self.api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

    def _call_gemini(self, payload):
        if not self.api_key:
            return {"status": "error", "message": "AI API Key missing. Set GEMINI_API_KEY in .env"}
            
        try:
            headers = {'Content-Type': 'application/json'}
            params = {'key': self.api_key}
            
            response = requests.post(self.api_url, json=payload, headers=headers, params=params)
            data = response.json()
            
            if 'error' in data:
                return {"status": "error", "message": data['error'].get('message', 'Unknown AI Error')}
                
            if 'candidates' in data:
                content = data['candidates'][0]['content']['parts'][0]['text']
                return {"status": "success", "content": content}
            
            return {"status": "error", "message": "AI returned no content"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def analyze_logs(self, logs):
        """
        Analyzes a list of Daily Logs (Notes) and provides insights.
        """
        # Prepare the prompt
        log_text = "\n".join([f"- {log.created_at.strftime('%Y-%m-%d')}: {log.content}" for log in logs])
        prompt = f"""
        You are an expert Agronomist AI. Analyze the following farm logs from the last 7 days and provide:
        1. A summary of activities.
        2. Potential risks (pests, weather, delays).
        3. Recommended next steps for the farmer.
        
        Logs:
        {log_text}
        
        Keep the response concise and formatted in HTML (using <ul>, <li>, <strong> tags).
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        return self._call_gemini(payload)

    def ask_crop_doctor(self, crop_name, sowing_date=None):
        """
        Provides Advice for a specific Crop.
        """
        context = f"Planted on {sowing_date}" if sowing_date else "Planning to plant"
        prompt = f"""
        You are an expert Agronomist. The farmer is asking about '{crop_name}' ({context}).
        Provide a concise HTML response covering:
        1. 🐛 Common Pests & Diseases to watch out for NOW.
        2. 💧 Watering & Care tips.
        3. ⏳ Estimated Harvest time from now.
        
        Keep it brief and practical. Use bullet points.
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        return self._call_gemini(payload)

    def diagnose_from_image(self, image_bytes, mime_type="image/jpeg"):
        """
        Analyzes a crop image to identify diseases.
        """
        # Encode image to base64
        img_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        prompt = """
        Analyze this crop image. 
        1. Identify the crop and any visible disease/pest.
        2. Estimate Severity (Mild/Moderate/Severe).
        3. Suggest a practical treatment.
        
        Return the result as a VALID JSON object with the following keys. Do NOT wrap in markdown code blocks.
        { "disease_name": "...", "severity": "...", "treatment": "...", "confidence": "..." }
        """
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": img_b64
                        }
                    }
                ]
            }]
        }
        return self._call_gemini(payload)

    def recommend_crops(self, area, season, location="India"):
        """
        Suggests profitable crops based on season and area.
        """
        prompt = f"""
        Act as an Agriculture Business Consultant.
        The user has {area} of land available in {season} (Location: {location}).
        
        Suggest 3 most profitable vegetable/crop options.
        For each option, provide:
        1. 💰 **Estimated Profit Potential** (High/Med/Low)
        2. ⏳ **Duration** (Days to harvest)
        3. 💡 **Why this crop?** (Market demand, weather suitability)
        
        Format the response as a clean HTML table or list.
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        return self._call_gemini(payload)

    def get_crop_duration(self, crop_name):
        """
        Returns the estimated duration in days for a crop.
        """
        prompt = f"""
        How many days does '{crop_name}' typically take from sowing to harvest?
        Return ONLY the number of days as an integer (e.g. 90). 
        If it varies, give a safe average.
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        result = self._call_gemini(payload)
        
        if result['status'] == 'success':
            import re
            match = re.search(r'\d+', result['content'])
            if match:
                return int(match.group())
        return None

# Singleton instance
ai_advisor = FarmAI()
