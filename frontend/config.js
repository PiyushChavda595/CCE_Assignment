/**
 * CampusCare Frontend Configuration
 *
 * This configuration allows seamless switching between:
 *  1. Local Development (Flask running on http://127.0.0.1:5000)
 *  2. AWS Production (AWS Lambda Function URL)
 *
 * You can configure the API endpoint here, or override it at runtime:
 *  - Via URL query parameter: ?api=https://your-lambda-url.on.aws
 *  - Via the in-app "Endpoint Settings" dialog
 */
const CAMPUSCARE_CONFIG = {
  // Default API endpoint:
  // - Local dev: "http://127.0.0.1:5000/api/reports"
  // - AWS Production: Replace with your AWS Lambda Function URL, e.g.:
  //   "https://abcdef123456789.lambda-url.ap-south-1.on.aws"
  DEFAULT_API_URL: "http://127.0.0.1:5000/api/reports",

  // Supported image extensions and maximum upload size (5 MB limit per assignment)
  ALLOWED_IMAGE_TYPES: ["image/jpeg", "image/png", "image/webp"],
  MAX_IMAGE_SIZE_BYTES: 5 * 1024 * 1024, // 5 MB

  // Storage key for runtime override
  STORAGE_KEY_API_URL: "campuscare_custom_api_url",

  /**
   * Resolve active API URL in order of priority:
   * 1. URL search param: ?api=...
   * 2. LocalStorage override (saved from in-app settings)
   * 3. window.CAMPUSCARE_API_URL if injected
   * 4. DEFAULT_API_URL
   */
  getActiveApiUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      const queryApi = params.get("api");
      if (queryApi && queryApi.trim()) {
        const clean = queryApi.trim().replace(/\/+$/, "");
        localStorage.setItem(this.STORAGE_KEY_API_URL, clean);
        return clean;
      }

      const stored = localStorage.getItem(this.STORAGE_KEY_API_URL);
      if (stored && stored.trim()) {
        return stored.trim().replace(/\/+$/, "");
      }
    } catch (e) {
      console.warn("Could not access localStorage or search params:", e);
    }

    if (window.CAMPUSCARE_API_URL && typeof window.CAMPUSCARE_API_URL === "string") {
      return window.CAMPUSCARE_API_URL.trim().replace(/\/+$/, "");
    }

    return this.DEFAULT_API_URL;
  },

  /**
   * Set and save a new API URL at runtime
   */
  setActiveApiUrl(url) {
    if (!url || !url.trim()) {
      localStorage.removeItem(this.STORAGE_KEY_API_URL);
    } else {
      localStorage.setItem(this.STORAGE_KEY_API_URL, url.trim().replace(/\/+$/, ""));
    }
  },

  /**
   * Reset to default configuration
   */
  resetToDefault() {
    localStorage.removeItem(this.STORAGE_KEY_API_URL);
  }
};

window.CAMPUSCARE_CONFIG = CAMPUSCARE_CONFIG;
