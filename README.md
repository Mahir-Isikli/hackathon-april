# hackathon-april
# AI Companion Caller - Backend
## Hackathon Project (April 5th-6th, 2024)

This repository contains the **backend server** for the AI Companion Caller project, developed for the hackathon held on April 5th-6th, 2024.

**Frontend Repository**: [https://github.com/jouv1/coucou](https://github.com/jouv1/coucou)

This FastAPI application acts as the bridge between Twilio (for handling phone calls) and ElevenLabs (for providing a conversational AI agent). It manages call state, retrieves user/loved one profiles from Supabase, and initiates/receives calls.

## How it Works

1.  **Data Storage:** User profiles, loved one details, call preferences, and conversation transcripts are stored in a Supabase database.
2.  **Conversational AI:** An ElevenLabs Conversational AI agent handles the actual conversation during the call.
3.  **Telephony:** Twilio is used for managing the phone call infrastructure (receiving inbound calls, making outbound calls, streaming audio).

### Inbound Calls (`/twilio/inbound_call`)

*   A user calls the Twilio phone number associated with this service.
*   Twilio sends a webhook request to the `/twilio/inbound_call` endpoint.
*   This server responds with TwiML instructions to connect the call to a WebSocket stream (`/media-stream`).
*   The `/media-stream` endpoint handles the real-time audio communication between Twilio and the ElevenLabs agent via the `TwilioAudioInterface`.
*   Before the agent starts, ElevenLabs calls the `/twilio/conversation-initiation` webhook to fetch dynamic data (like caller name, loved one profile) based on the caller's phone number from Supabase.

### Outbound Calls (`/initiate_call/{phone_number}`)

*   A request is made to the `/initiate_call/{phone_number}` endpoint (e.g., triggered by a scheduler or another service).
*   The server fetches the profile for the specified `phone_number` from Supabase.
*   It then uses the ElevenLabs API to initiate an outbound call *from* the configured ElevenLabs agent phone number *to* the target `phone_number`.
*   Dynamic data (profile information, time of day, etc.) is passed to the ElevenLabs agent during initiation.
*   Once the call connects, the flow is similar to the inbound call, using the WebSocket stream for audio.

### Call End (`/twilio/call-end`)

*   When a call managed by ElevenLabs ends, ElevenLabs sends a webhook notification to the `/twilio/call-end` endpoint.
*   This endpoint verifies the webhook signature, extracts the call transcript and metadata (duration, sentiment), finds the corresponding user in Supabase (creating one if necessary), and saves the conversation details.

## Setup

1.  **Clone the repository (if you haven't already):**
    ```bash
    git clone <your-repository-url>
    cd hackathon
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    # On Windows
    # .\.venv\Scripts\activate
    # On macOS/Linux
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up environment variables:**
    Copy the example environment file:
    ```bash
    cp .env.example .env
    ```
    Now, open the newly created `.env` file in your editor and fill in your actual credentials for each variable:
    ```dotenv
    # Contents of .env file after filling in values
    ELEVENLABS_AGENT_ID=your_actual_agent_id
    ELEVENLABS_API_KEY=your_actual_api_key
    ELEVENLABS_AGENT_PHONE_ID=your_actual_agent_phone_id 
    SUPABASE_URL=https://your-project.supabase.co
    SUPABASE_SERVICE_ROLE_KEY=your_actual_service_role_key
    WEBHOOK_SECRET=your_actual_webhook_secret
    ```
    *   `ELEVENLABS_AGENT_PHONE_ID`: Find this in your ElevenLabs Voice settings under the specific agent phone number.
    *   `WEBHOOK_SECRET`: Set this in your ElevenLabs agent settings under 'Call Termination Webhook'.

## Running Locally

1.  **Start the FastAPI server:**
    ```bash
    uvicorn main:app --reload --port 8000
    ```

2.  **Expose local server using ngrok:**
    Since Twilio and ElevenLabs need to send webhooks to your server, you need to expose your local `localhost:8000` to the internet. Use a tool like ngrok:
    ```bash
    ngrok http 8000
    ```
    ngrok will provide you with a public HTTPS URL (e.g., `https://<unique_id>.ngrok-free.app`).

3.  **Configure Webhooks:**
    *   **Twilio:** Update your Twilio phone number's voice settings to use the ngrok URL followed by `/twilio/inbound_call` for incoming calls.
    *   **ElevenLabs:** Update your agent's 'Conversation Initiation Webhook' to use the ngrok URL followed by `/twilio/conversation-initiation`.
    *   **ElevenLabs:** Update your agent's 'Call Termination Webhook' to use the ngrok URL followed by `/twilio/call-end` and ensure the `WEBHOOK_SECRET` matches.

Now you can test inbound calls by calling your Twilio number and outbound calls by making a GET request to `http://localhost:8000/initiate_call/{phone_number}` (or the ngrok equivalent if calling from outside your local machine). 
