import os
import json
import traceback
import hmac
import hashlib
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, HTTPException
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation
from elevenlabs import ConversationInitiationClientDataRequestInput
from twilio_audio_interface import TwilioAudioInterface
from starlette.websockets import WebSocketDisconnect
from supabase import create_client, Client
import httpx
import datetime

load_dotenv()

# Load environment variables
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
ELEVENLABS_AGENT_PHONE_ID = os.getenv("ELEVENLABS_AGENT_PHONE_ID")

# Initialize Supabase client with the service_role key
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Initialize ElevenLabs client
eleven_labs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Twilio-ElevenLabs Integration Server"}

@app.get("/get-caller-name")
async def get_caller_name(phone_number: str):
    """
    Endpoint that takes a phone number and returns the caller's name from Supabase.
    Example: /get-caller-name?phone_number=+1234567890
    """
    # Normalize the phone number
    normalized_number = phone_number.strip().replace(" ", "")
    if not normalized_number.startswith("+"):
        normalized_number = "+" + normalized_number
    
    try:
        # Query Supabase for the user with the matching phone_number
        response = supabase.table("users").select("user_name").eq("phone_number", normalized_number).execute()
        
        # Check if a user was found
        if response.data and len(response.data) > 0:
            # Return the user_name from the first matching row
            return {"name": response.data[0]["user_name"]}
        else:
            # Return a default name for unknown callers
            return {"name": "Valued Customer"}
    
    except Exception as e:
        print(f"Error querying Supabase: {str(e)}")
        # Fallback to default name in case of an error
        return {"name": "Valued Customer"}

@app.post("/twilio/inbound_call")
async def handle_incoming_call(request: Request):
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "Unknown")
    from_number = form_data.get("From", "Unknown")
    print(f"Incoming call: CallSid={call_sid}, From={from_number}")

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{request.url.hostname}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.post("/twilio/conversation-initiation")
async def handle_conversation_initiation(request: Request):
    try:
        # Parse the request body
        data = await request.json()
        print(f"Received conversation initiation: {data}")

        # Extract the caller's phone number
        caller_id = data.get("caller_id", None)

        if not caller_id:
            print("Caller ID not found in request")
            return {
                "type": "conversation_initiation_client_data",
                "dynamic_variables": {
                    "caller_name": "there"
                }
            }

        # Fetch the loved one's profile using the query parameter format
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://520d-83-135-183-58.ngrok-free.app/get-loved-one-profile?phone_number={caller_id}"
            )
            response.raise_for_status()
            profile = response.json()
            
            # Print the full profile data for debugging
            print(f"Retrieved profile data: {profile}")
            
            # Check if there was an error
            if "error" in profile:
                print(f"Error in profile data: {profile['error']}")
                return {
                    "type": "conversation_initiation_client_data",
                    "dynamic_variables": {
                        "caller_name": profile.get("caller_name", "there")
                    }
                }
            
            # Create dynamic variables for the conversation in a format that's easy for the agent to use
            dynamic_variables = {
                # Caller information
                "caller_name": profile.get("caller", {}).get("name", "there"),
                
                # Loved one information
                "loved_one_name": profile.get("loved_one", {}).get("name", ""),
                "loved_one_nickname": profile.get("loved_one", {}).get("nickname", ""),
                "loved_one_gender": profile.get("loved_one", {}).get("gender", ""),
                "loved_one_relationship": profile.get("loved_one", {}).get("relationship", ""),
                
                # Medication information - in a simple, direct format
                "has_medications": str(profile.get("medications", {}).get("has_medications", False)).lower(),
                "morning_medications": profile.get("medications", {}).get("morning_medications", "none"),
                "afternoon_medications": profile.get("medications", {}).get("afternoon_medications", "none"),
                "evening_medications": profile.get("medications", {}).get("evening_medications", "none"),
                
                # Call settings
                "call_length": profile.get("call_settings", {}).get("length", "medium"),
                "voice_preference": profile.get("call_settings", {}).get("voice", "female"),
                "call_frequency": profile.get("call_settings", {}).get("frequency", "daily check ins"),
                
                # Checklist items - as simple boolean strings
                "check_medications": str(profile.get("call_settings", {}).get("checklist", {}).get("medication_reminders", False)).lower(),
                "check_sleep": str(profile.get("call_settings", {}).get("checklist", {}).get("sleep_quality", False)).lower(),
                "check_mood": str(profile.get("call_settings", {}).get("checklist", {}).get("mood_check", False)).lower(),
                "check_appointments": str(profile.get("call_settings", {}).get("checklist", {}).get("upcoming_appointments", False)).lower(),
                
                # Notification settings
                "notify_daily_summary": str(profile.get("notifications", {}).get("daily_summary", False)).lower(),
                "notify_missed_calls": str(profile.get("notifications", {}).get("missed_calls", False)).lower(),
                "notify_low_sentiment": str(profile.get("notifications", {}).get("low_sentiment", False)).lower()
            }

            # Add current time information to help with medication timing
            now = datetime.datetime.now()
            hour = now.hour
            
            if 5 <= hour < 12:
                time_of_day = "morning"
            elif 12 <= hour < 17:
                time_of_day = "afternoon"
            else:
                time_of_day = "evening"
                
            dynamic_variables["time_of_day"] = time_of_day

        return {
            "type": "conversation_initiation_client_data",
            "dynamic_variables": dynamic_variables
        }

    except Exception as e:
        print(f"Error in conversation initiation webhook: {str(e)}")
        traceback.print_exc()
        # Fallback response if there's an error
        return {
            "type": "conversation_initiation_client_data",
            "dynamic_variables": {
                "caller_name": "there"
            }
        }

@app.post("/twilio/call-end")
async def handle_call_end(request: Request):
    """
    Webhook endpoint to handle call end notifications from ElevenLabs.
    Extracts the transcript, call duration, happiness level, and call direction from the payload and saves it to Supabase.
    """
    # Log the headers
    print(f"Request headers: {request.headers}")

    # Get the signature from the headers
    signature_header = request.headers.get("ElevenLabs-Signature")
    if not signature_header:
        print("Missing ElevenLabs-Signature header")
        raise HTTPException(status_code=401, detail="Missing ElevenLabs-Signature header")

    # Parse the ElevenLabs-Signature header (format: t=<timestamp>,v0=<signature>)
    signature_parts = dict(part.split("=") for part in signature_header.split(","))
    timestamp = signature_parts.get("t")
    provided_signature = signature_parts.get("v0")
    if not timestamp or not provided_signature:
        print("Invalid ElevenLabs-Signature format")
        raise HTTPException(status_code=401, detail="Invalid ElevenLabs-Signature format")

    # Get the raw request body
    body = await request.body()
    body_str = body.decode("utf-8")
    print(f"Request body: {body_str}")

    # Compute the HMAC signature using timestamp and body (format: <timestamp>.<body>)
    message = f"{timestamp}.{body_str}".encode("utf-8")
    expected_signature = hmac.new(
        key=WEBHOOK_SECRET.encode("utf-8"),
        msg=message,
        digestmod=hashlib.sha256
    ).hexdigest()
    print(f"Computed signature: {expected_signature}")
    print(f"Provided signature: {provided_signature}")

    if not hmac.compare_digest(expected_signature, provided_signature):
        print("Invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse the request body
    data = json.loads(body_str)
    print(f"Received call end notification: {data}")

    # Extract conversation_id and caller_id from the nested structure
    conversation_id = data.get("data", {}).get("conversation_id")
    caller_id = data.get("data", {}).get("metadata", {}).get("phone_call", {}).get("external_number")

    # Fallback to conversation_initiation_client_data if caller_id is missing
    if not caller_id:
        caller_id = data.get("conversation_initiation_client_data", {}).get("dynamic_variables", {}).get("system__caller_id")

    if not conversation_id or not caller_id:
        print("Missing conversation_id or caller_id in call end notification")
        return {"status": "error", "message": "Missing required fields"}

    try:
        # Extract the transcript directly from the payload
        transcript = data.get("data", {}).get("transcript", [])
        if not transcript:
            print("No transcript found in payload")
            return {"status": "error", "message": "No transcript available"}

        # Format the transcript as a string
        transcript_lines = []
        for entry in transcript:
            role = entry.get("role", "unknown")
            message = entry.get("message", "")
            if message:  # Only include entries with a message
                transcript_lines.append(f"{role.capitalize()}: {message}")
        full_transcript = "\n".join(transcript_lines)
        print(f"Formatted transcript:\n{full_transcript}")

        # Extract the additional data
        metadata = data.get("data", {}).get("metadata", {})
        analysis = data.get("analysis", {})

        # Extract call duration, happiness level, and call direction
        call_duration_secs = metadata.get("call_duration_secs")
        happiness_data = analysis.get("data_collection_results", {}).get("happy does the person seem?", {})
        happiness_level = happiness_data.get("value")
        phone_call = metadata.get("phone_call", {})
        call_direction = phone_call.get("direction")

        # Look up the user_id based on the phone number
        normalized_number = caller_id.strip().replace(" ", "")
        if not normalized_number.startswith("+"):
            normalized_number = "+" + normalized_number

        user_response = supabase.table("users").select("id").eq("phone_number", normalized_number).execute()
        if user_response.data and len(user_response.data) > 0:
            user_id = user_response.data[0]["id"]
        else:
            # If the user doesn't exist, create a new user
            new_user = supabase.table("users").insert({
                "phone_number": normalized_number,
                "user_name": "Unknown User"
            }).execute()
            user_id = new_user.data[0]["id"]

        # Insert the transcript and additional data into the conversations table
        conversation_data = {
            "user_id": user_id,
            "phone_number": normalized_number,
            "transcript": full_transcript,
            "call_duration_secs": call_duration_secs,
            "happiness_level": happiness_level,
            "call_direction": call_direction
        }
        supabase.table("conversations").insert(conversation_data).execute()
        print(f"Transcript and additional data saved to Supabase for user_id: {user_id}")

        return {"status": "success", "message": "Transcript and additional data saved"}

    except Exception as e:
        print(f"Error saving data to Supabase: {str(e)}")
        return {"status": "error", "message": str(e)}
    
@app.get("/get-loved-one-profile")
async def get_loved_one_profile_query(phone_number: str):
    """
    Endpoint that takes a phone number as a query parameter and returns a clean, 
    structured profile for the agent to use.
    """
    # Normalize the phone number
    normalized_number = phone_number.strip().replace(" ", "")
    if not normalized_number.startswith("+"):
        normalized_number = "+" + normalized_number
    
    try:
        # Query Supabase for the user with the matching phone_number
        user_response = supabase.table("users").select("id, user_name").eq("phone_number", normalized_number).execute()
        
        # Check if a user was found
        if not user_response.data or len(user_response.data) == 0:
            print(f"User not found for phone number: {normalized_number}")
            return {"caller_name": "Valued Customer", "error": "User not found"}
        
        user_id = user_response.data[0]["id"]
        user_name = user_response.data[0]["user_name"]
        print(f"Found user: {user_name} with id: {user_id}")
        
        # Get the loved one profile
        loved_one_response = supabase.table("loved_ones").select("*").eq("user_id", user_id).execute()
        if not loved_one_response.data or len(loved_one_response.data) == 0:
            print(f"No loved one found for user_id: {user_id}")
            return {
                "caller_name": user_name,
                "error": "No loved one profile found"
            }
        
        loved_one = loved_one_response.data[0]
        loved_one_id = loved_one["id"]
        print(f"Found loved one: {loved_one['name']} with id: {loved_one_id}")
        
        # Get medications
        medications_response = supabase.table("medications").select("*").eq("loved_one_id", loved_one_id).execute()
        medications = medications_response.data
        
        # Get call preferences
        call_prefs_response = supabase.table("call_preferences").select("*").eq("loved_one_id", loved_one_id).execute()
        call_preferences = call_prefs_response.data[0] if call_prefs_response.data else {}
        
        # Get notification settings
        notif_response = supabase.table("notification_settings").select("*").eq("loved_one_id", loved_one_id).execute()
        notification_settings = notif_response.data[0] if notif_response.data else {}
        
        # Get upcoming appointments
        appointments_response = supabase.table("consolidated_appointments").select("*").eq("loved_one_id", loved_one_id).execute()
        appointments = appointments_response.data
        
        # Process medications into a cleaner format
        morning_meds = []
        afternoon_meds = []
        evening_meds = []
        
        for med in medications:
            med_name = med["medication_name"]
            time_taken = med.get("time_taken", [])
            
            # Handle both list and string formats
            if isinstance(time_taken, list):
                times = [t.lower() if isinstance(t, str) else str(t).lower() for t in time_taken]
            else:
                # If it's a string, split it into a list
                times = [t.strip().lower() for t in str(time_taken).split(',')]
            
            if any('morning' in t for t in times):
                morning_meds.append(med_name)
            if any('afternoon' in t for t in times):
                afternoon_meds.append(med_name)
            if any('evening' in t for t in times):
                evening_meds.append(med_name)
        
        # Process appointments
        upcoming_appointments = []
        for appt in appointments:
            upcoming_appointments.append({
                "title": appt["appointment_title"],
                "date": appt["appointment_date"],
                "time": appt["appointment_time"],
                "frequency": appt["frequency"]
            })
        
        # Construct a clean, simplified profile
        clean_profile = {
            "caller": {
                "name": user_name
            },
            "loved_one": {
                "name": loved_one["name"],
                "nickname": loved_one["nickname"],
                "age_range": loved_one["age_range"],
                "gender": loved_one["gender"],
                "relationship": loved_one["relationship_to_user"]
            },
            "medications": {
                "has_medications": len(medications) > 0,
                "morning_medications": ", ".join(morning_meds) if morning_meds else "none",
                "afternoon_medications": ", ".join(afternoon_meds) if afternoon_meds else "none",
                "evening_medications": ", ".join(evening_meds) if evening_meds else "none"
            },
            "call_settings": {
                "length": call_preferences.get("call_length", "medium"),
                "voice": call_preferences.get("voice_preference", "female"),
                "frequency": call_preferences.get("call_frequency", "daily check ins"),
                "checklist": {
                    "medication_reminders": call_preferences.get("medication_reminders", False),
                    "sleep_quality": call_preferences.get("sleep_quality", False),
                    "mood_check": call_preferences.get("mood_check", False),
                    "upcoming_appointments": call_preferences.get("upcoming_appointments", False)
                }
            },
            "notifications": {
                "daily_summary": notification_settings.get("daily_call_summary", False),
                "missed_calls": notification_settings.get("missed_calls", False),
                "low_sentiment": notification_settings.get("low_sentiment", False)
            },
            "appointments": upcoming_appointments
        }
        
        print(f"Successfully built profile for {user_name}'s loved one {loved_one['name']}")
        return clean_profile
    
    except Exception as e:
        print(f"Error querying Supabase: {str(e)}")
        traceback.print_exc()  # Add full traceback for better debugging
        return {"caller_name": "Valued Customer", "error": str(e)}

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connection opened")

    audio_interface = TwilioAudioInterface(websocket)
    eleven_labs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    try:
        conversation = Conversation(
            client=eleven_labs_client,
            agent_id=ELEVENLABS_AGENT_ID,
            requires_auth=True,
            audio_interface=audio_interface,
            callback_agent_response=lambda text: print(f"Agent: {text}"),
            callback_user_transcript=lambda text: print(f"User: {text}"),
        )

        conversation.start_session()
        print("Conversation started")

        async for message in websocket.iter_text():
            if not message:
                continue
            await audio_interface.handle_twilio_message(json.loads(message))

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception:
        print("Error occurred in WebSocket handler:")
        traceback.print_exc()
    finally:
        try:
            conversation.end_session()
            conversation.wait_for_session_end()
            print("Conversation ended")
        except Exception:
            print("Error ending conversation session:")
            traceback.print_exc()

@app.get("/initiate_call/{phone_number}")
async def initiate_call(phone_number: str, request: Request):
    """
    Endpoint to initiate an outbound call to a specified phone number.
    Example: /initiate_call/+1234567890
    """
    print(f"Initiating call to phone number: {phone_number}")
    
    # Normalize the phone number
    normalized_number = phone_number.strip().replace(" ", "")
    if not normalized_number.startswith("+"):
        normalized_number = "+" + normalized_number
    
    try:
        # Get the server host for the API call
        server_host = request.headers.get("host", request.url.hostname)
        server_scheme = request.url.scheme
        
        # Use the local endpoint directly
        profile = await get_loved_one_profile_query(normalized_number)
        
        # Print the full profile data for debugging
        print(f"Retrieved profile data: {profile}")
        
        # Check if there was an error
        if "error" in profile:
            print(f"Error in profile data: {profile['error']}")
            return {"status": "error", "message": profile['error']}
        
        # Create dynamic variables for the conversation with focus on locations and appointments
        dynamic_variables = {
            # Caller information
            "caller_name": profile.get("caller", {}).get("name", "there"),
            
            # Loved one information
            "loved_one_name": profile.get("loved_one", {}).get("name", ""),
            "loved_one_nickname": profile.get("loved_one", {}).get("nickname", ""),
            "loved_one_gender": profile.get("loved_one", {}).get("gender", ""),
            "loved_one_relationship": profile.get("loved_one", {}).get("relationship", ""),
            
            # Medication information
            "has_medications": str(profile.get("medications", {}).get("has_medications", False)).lower(),
            "morning_medications": profile.get("medications", {}).get("morning_medications", "none"),
            "afternoon_medications": profile.get("medications", {}).get("afternoon_medications", "none"),
            "evening_medications": profile.get("medications", {}).get("evening_medications", "none"),
            
            # Call settings
            "call_length": profile.get("call_settings", {}).get("length", "medium"),
            "voice_preference": profile.get("call_settings", {}).get("voice", "female"),
            "call_frequency": profile.get("call_settings", {}).get("frequency", "daily check ins"),
            
            # Checklist items
            "check_medications": str(profile.get("call_settings", {}).get("checklist", {}).get("medication_reminders", False)).lower(),
            "check_sleep": str(profile.get("call_settings", {}).get("checklist", {}).get("sleep_quality", False)).lower(),
            "check_mood": str(profile.get("call_settings", {}).get("checklist", {}).get("mood_check", False)).lower(),
            "check_appointments": str(profile.get("call_settings", {}).get("checklist", {}).get("upcoming_appointments", False)).lower(),
            
            # Notification settings
            "notify_daily_summary": str(profile.get("notifications", {}).get("daily_summary", False)).lower(),
            "notify_missed_calls": str(profile.get("notifications", {}).get("missed_calls", False)).lower(),
            "notify_low_sentiment": str(profile.get("notifications", {}).get("low_sentiment", False)).lower()
        }
        
        # Add upcoming appointments information with a special focus
        appointments = profile.get("appointments", [])
        if appointments:
            # Add information about the next appointment
            next_appt = appointments[0]
            dynamic_variables["has_upcoming_appointment"] = "true"
            dynamic_variables["next_appointment_title"] = next_appt.get("title", "")
            dynamic_variables["next_appointment_date"] = next_appt.get("date", "")
            dynamic_variables["next_appointment_time"] = next_appt.get("time", "")
            
            # Create a formatted string for all appointments
            appt_details = []
            for i, appt in enumerate(appointments[:3]):  # Limit to first 3 appointments
                appt_details.append(f"{appt.get('title')} on {appt.get('date')} at {appt.get('time')}")
            
            dynamic_variables["upcoming_appointments"] = ", ".join(appt_details)
        else:
            dynamic_variables["has_upcoming_appointment"] = "false"
            dynamic_variables["upcoming_appointments"] = "none"
        
        # Add current time information
        now = datetime.datetime.now()
        hour = now.hour
        
        if 5 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 17:
            time_of_day = "afternoon"
        else:
            time_of_day = "evening"
            
        dynamic_variables["time_of_day"] = time_of_day
        
        # Initialize ElevenLabs client
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        
        # Prepare the conversation initiation data as a dictionary
        conversation_data = {
            "type": "conversation_initiation_client_data",
            "dynamic_variables": dynamic_variables
        }
        
        # Initiate the outbound call
        print(f"Initiating outbound call to {normalized_number} with agent {ELEVENLABS_AGENT_ID}")
        response = client.conversational_ai.twilio_outbound_call(
            agent_id=ELEVENLABS_AGENT_ID,
            agent_phone_number_id=ELEVENLABS_AGENT_PHONE_ID,
            to_number=normalized_number,
            conversation_initiation_client_data=conversation_data
        )
        
        print(f"Call initiated successfully: {response}")
        return {"status": "success", "call_sid": response.get("callSid", "")}
        
    except Exception as e:
        print(f"Error initiating call: {str(e)}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)