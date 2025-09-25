import asyncio
from pydantic import Field
from typing import Dict, Any, Annotated
from ..utils import make_api_request, get_api_credentials
from utils.log_utils import setup_logger
from fastmcp.server.dependencies import get_context

logger = setup_logger(__name__)


async def get_appointment_categories() -> Dict[str, Any]:
    """Retrieves the master list of all appointment scheduling categories."""
    logger.info("Attempting to get master list of all appointment categories.")
    try:
        ctx = get_context()
        endpoint = "master/appointments/categories"
        logger.debug(f"Making GET request to endpoint: {endpoint}")
        response = await make_api_request(ctx, "GET", endpoint)

        if not response.get("success"):
            logger.error(f"API call to get appointment categories failed. Response: {response}")
            return response

        categories_data = response.get("message", {}).get("body", {}).get("items", [])
        logger.info(f"Successfully received {len(categories_data)} categories from API.")

        formatted_categories = []
        for cat in categories_data:
            try:
                formatted_categories.append({"categoryId": cat["id"], "name": cat["name"]})
            except (KeyError, TypeError) as e:
                logger.warning(f"Skipping malformed category item due to {e}. Item: {cat}")
                continue

        logger.info(f"Successfully formatted {len(formatted_categories)} categories.")
        return {"success": True, "categories": formatted_categories}
    except Exception as e:
        logger.exception("An unexpected error occurred in get_appointment_categories.")
        return {"success": False, "message": f"An internal server error occurred: {e}"}


async def get_category_events(
    category_id: Annotated[str, Field(..., description="The unique ID of the appointment category.")],
) -> Dict[str, Any]:
    """
    Finds the specific reasons for a visit (events) for a given category.
    """
    logger.info(f"Attempting to get events for category ID: {category_id}")
    try:
        ctx = get_context()
        endpoint = f"master/appointments/categories/{category_id}/events"
        logger.debug(f"Making GET request to endpoint: {endpoint}")
        response = await make_api_request(ctx, "GET", endpoint)

        if not response.get("success"):
            logger.error(f"API call to get category events failed for categoryId {category_id}. Response: {response}")
            return response

        events_data = response.get("message", {}).get("body", {}).get("items", [])
        logger.info(f"Successfully received {len(events_data)} events from API for categoryId {category_id}.")

        formatted_events = []
        for event in events_data:
            try:
                formatted_events.append({"eventId": event["id"], "name": event["name"]})
            except (KeyError, TypeError) as e:
                logger.warning(f"Skipping malformed event item due to {e}. Item: {event}")
                continue

        logger.info(f"Successfully formatted {len(formatted_events)} events.")
        return {"success": True, "events": formatted_events}
    except Exception as e:
        logger.exception(f"An unexpected error occurred in get_category_events for categoryId {category_id}.")
        return {"success": False, "message": f"An internal server error occurred: {e}"}


async def get_available_slots(
    category_id: Annotated[str, Field(..., description="The unique ID of the appointment category to search within.")],
    start_date: Annotated[str, Field(..., description="The desired date for the appointment in YYYY-MM-DD format.")],
) -> Dict[str, Any]:
    """Finds available appointment slots for a given scheduling category and date at the default location."""
    logger.info(f"Searching for available slots in category ID: {category_id} on date: {start_date}")
    try:
        ctx = get_context()
        creds = await get_api_credentials(ctx)
        location_id = creds.get("LOCATION_ID")

        if not location_id:
            logger.error("A location ID is required but could not be found in headers or .env.")
            return {"success": False, "message": "Search cannot be performed because no location is configured."}

        logger.info(f"Filtering by location ID: {location_id}")
        filter_string = f"categoryId eq guid'{category_id}' and startDate eq dateTime'{start_date}' and locationId eq guid'{location_id}'"
        params = {"$filter": filter_string}

        logger.debug(f"Making GET request to 'appointments/slots' with params: {params}")
        response = await make_api_request(ctx, "GET", "appointments/slots", params=params)

        if not response.get("success"):
            logger.error(f"API call to get available slots failed. Response: {response}")
            return response

        slots_data = response.get("message", {}).get("body", {}).get("items", [])
        logger.info(f"Received {len(slots_data)} total slots from API.")

        available_slots = []
        for slot in slots_data:
            try:
                timeslot_count = slot.get("timeslotCount", 0)
                appointment_count = slot.get("appointmentCount", 0)
                if timeslot_count > appointment_count:
                    available_slots.append(slot)
            except TypeError as e:
                logger.warning(f"Could not process a slot due to invalid data type. Error: {e}. Slot: {slot}")

        logger.info(f"Found {len(available_slots)} available slots after filtering.")
        return {"success": True, "available_slots": available_slots}
    except Exception as e:
        logger.exception("An unexpected error occurred in get_available_slots.")
        return {"success": False, "message": f"An internal server error occurred: {e}"}


async def get_patient_appointments(
    person_id: Annotated[str, Field(..., description="The unique ID of the patient (personId).")],
) -> Dict[str, Any]:
    """Retrieves a list of a patient's upcoming appointments with full details."""
    logger.info(f"Attempting to get appointments for personId: {person_id}")
    try:
        ctx = get_context()
        summary_endpoint = f"persons/{person_id}/appointments"
        logger.debug(f"Making GET request to summary endpoint: {summary_endpoint}")
        summary_response = await make_api_request(ctx, "GET", summary_endpoint)

        if not summary_response.get("success"):
            logger.error(f"Failed to get appointment summary for personId {person_id}. Response: {summary_response}")
            return summary_response

        appointments_summary = summary_response.get("message", {}).get("body", {}).get("items", [])
        if not appointments_summary:
            logger.info(f"Patient with personId {person_id} has no upcoming appointments.")
            return {"success": True, "message": "This patient has no upcoming appointments."}

        logger.info(f"Found {len(appointments_summary)} appointments in summary for personId {person_id}.")
        appt_id_to_category_map = {appt.get("appointmentId"): appt.get("categoryIds") for appt in appointments_summary}

        async def get_appointment_details(appt_summary: Dict[str, Any]):
            appt_id = appt_summary.get("appointmentId")
            if not appt_id:
                logger.warning(f"Found an appointment summary with no appointmentId: {appt_summary}")
                return None
            try:
                detail_endpoint = f"appointments/{appt_id}"
                logger.debug(f"Fetching details for appointmentId: {appt_id} from endpoint: {detail_endpoint}")
                detail_response = await make_api_request(ctx, "GET", detail_endpoint)
                if detail_response.get("success"):
                    return detail_response.get("message", {}).get("body", {})
                else:
                    logger.error(f"Failed to get details for appointmentId {appt_id}. Response: {detail_response}")
                    return None
            except Exception:
                logger.exception(f"An unexpected error occurred while fetching details for appointmentId {appt_id}.")
                return None

        tasks = [get_appointment_details(appt) for appt in appointments_summary]
        detailed_results = await asyncio.gather(*tasks)

        # Filter out None results from failed API calls
        valid_detailed_results = [res for res in detailed_results if res]
        logger.info(
            f"Successfully fetched details for {len(valid_detailed_results)} out of {len(appointments_summary)} appointments."
        )

        formatted_appointments = []
        for appt_details in valid_detailed_results:
            try:
                appt_id = appt_details.get("id")
                category_ids = appt_id_to_category_map.get(appt_id)

                full_date = "N/A"
                date_part = appt_details.get("appointmentDate", "").split("T")[0]
                begin_time = appt_details.get("beginTime", "")
                if date_part and begin_time:
                    formatted_time = f"{begin_time[:2]}:{begin_time[2:]}:00"
                    full_date = f"{date_part}T{formatted_time}"

                formatted_appointments.append(
                    {
                        "appointmentId": appt_id,
                        "fullAppointmentDate": full_date,
                        "duration": appt_details.get("duration"),
                        "locationName": appt_details.get("locationName"),
                        "locationId": appt_details.get("locationId"),
                        "resourceIds": appt_details.get("resourceIds"),
                        "eventName": appt_details.get("eventName"),
                        "eventId": appt_details.get("eventId"),
                        "categoryIds": category_ids,
                        "isCancelled": appt_details.get("isCancelled"),
                    }
                )
            except (AttributeError, IndexError, TypeError) as e:
                logger.error(f"Error formatting appointment details due to {e}. Details: {appt_details}")

        if not formatted_appointments and appointments_summary:
            logger.error("Could not retrieve details for any of the patient's appointments.")
            return {"success": False, "message": "Could not retrieve details for the patient's appointments."}

        return {"success": True, "appointments": formatted_appointments}
    except Exception as e:
        logger.exception(f"An unexpected error occurred in get_patient_appointments for personId {person_id}.")
        return {"success": False, "message": f"An internal server error occurred: {e}"}


async def book_appointment(
    person_id: Annotated[str, Field(..., description="The patient's unique personId.")],
    event_id: Annotated[str, Field(..., description="The unique eventId for the reason of visit.")],
    location_id: Annotated[str, Field(..., description="The unique locationId for the appointment.")],
    resource_id: Annotated[str, Field(..., description="The unique resourceId for the provider.")],
    appointment_date: Annotated[
        str, Field(..., description="The full start date and time for the appointment in ISO 8601 format.")
    ],
    duration_minutes: Annotated[int, Field(..., description="The duration of the appointment in minutes.")],
) -> Dict[str, Any]:
    """Books a new appointment for a patient."""
    logger.info(f"Attempting to book appointment for personId: {person_id} at {appointment_date}")
    try:
        ctx = get_context()
        payload = {
            "personId": person_id,
            "eventId": event_id,
            "locationId": location_id,
            "resourceIds": [resource_id],
            "appointmentDate": appointment_date,
            "durationMinutes": duration_minutes,
        }
        logger.debug(f"Making POST request to 'appointments' with payload: {payload}")
        response = await make_api_request(ctx, "POST", "appointments", json_data=payload)

        if not response.get("success"):
            logger.error(f"Failed to book appointment. Response: {response}")
            return response

        headers = response.get("message", {}).get("headers", {})
        location_header = headers.get("location") or headers.get("Location")

        if not location_header:
            logger.warning("Appointment was likely booked, but the 'location' header was missing in the response.")
            return {
                "success": True,
                "appointmentId": None,
                "message": "Appointment booked, but could not confirm the new ID.",
            }

        new_appointment_id = location_header.split("/")[-1]
        logger.info(f"Successfully booked appointment with ID: {new_appointment_id}")
        return {"success": True, "appointmentId": new_appointment_id, "message": "Appointment booked successfully."}

    except (AttributeError, IndexError, TypeError) as e:
        logger.exception(
            f"Appointment was likely booked, but could not parse the new ID from headers. Error: {e}. Headers: {headers}"
        )
        return {"success": True, "appointmentId": None, "message": "Appointment booked, but could not confirm the new ID."}
    except Exception as e:
        logger.exception("An unexpected error occurred in book_appointment.")
        return {"success": False, "message": f"An internal server error occurred: {e}"}


async def reschedule_appointment(
    appointment_id: Annotated[str, Field(..., description="The unique ID of the original appointment to be rescheduled.")],
    event_id: Annotated[str, Field(..., description="The unique eventId for the reason of visit.")],
    location_id: Annotated[str, Field(..., description="The unique locationId for the new appointment.")],
    resource_id: Annotated[str, Field(..., description="The unique resourceId for the provider for the new appointment.")],
    appointment_date: Annotated[
        str, Field(..., description="The new start date and time for the appointment in ISO 8601 format.")
    ],
    duration_minutes: Annotated[int, Field(..., description="The duration of the new appointment in minutes.")],
) -> Dict[str, Any]:
    """Updates (reschedules) an existing appointment to a new date, time, location, or provider."""
    logger.info(f"Attempting to reschedule appointment {appointment_id} to {appointment_date}")
    try:
        ctx = get_context()
        logger.info("Automatically fetching reschedule reasons.")
        params = {"$filter": "type eq 'as_resched_reason'"}
        reasons_response = await make_api_request(ctx, "GET", "master/list-items", params=params)

        if not reasons_response.get("success"):
            logger.error(f"Could not fetch reschedule reasons. API response: {reasons_response}")
            return {"success": False, "message": "Could not fetch reschedule reasons."}

        reasons_data = reasons_response.get("message", {}).get("body", {}).get("items", [])

        ## Search for the reschedule reason by name instead of a fixed index.
        reason_id_to_use = None
        target_reason_name = "Patient Request"
        for reason in reasons_data:
            if reason.get("name") == target_reason_name:
                reason_id_to_use = reason.get("id")
                break

        if not reason_id_to_use:
            logger.error(f"Could not find a reschedule reason with the name '{target_reason_name}'.")
            return {"success": False, "message": f"A valid reschedule reason ('{target_reason_name}') could not be found."}

        logger.info(f"Automatically selected reschedule reason ID: {reason_id_to_use}")

        payload = {
            "eventId": event_id,
            "locationId": location_id,
            "resourceIds": [resource_id],
            "appointmentDate": appointment_date,
            "durationMinutes": duration_minutes,
            "rescheduleReasonId": reason_id_to_use,
        }

        endpoint = f"appointments/{appointment_id}/reschedule"
        logger.debug(f"Making POST request to {endpoint} with payload: {payload}")
        response = await make_api_request(ctx, "POST", endpoint, json_data=payload)

        if not response.get("success"):
            logger.error(f"Failed to reschedule appointment {appointment_id}. Response: {response}")
            return response

        headers = response.get("message", {}).get("headers", {})
        location_header = headers.get("location") or headers.get("Location")

        if not location_header:
            logger.warning("Appointment was likely rescheduled, but 'location' header was missing.")
            return {
                "success": True,
                "newAppointmentId": None,
                "message": "Appointment rescheduled, but could not confirm the new ID.",
            }

        new_appointment_id = location_header.split("/")[-1]
        logger.info(f"Successfully rescheduled to new appointment with ID: {new_appointment_id}")
        return {"success": True, "newAppointmentId": new_appointment_id, "message": "Appointment rescheduled successfully."}
    except (AttributeError, IndexError, TypeError) as e:
        logger.exception(
            f"Appointment was likely rescheduled, but could not parse the new ID. Error: {e}. Headers: {headers}"
        )
        return {
            "success": True,
            "newAppointmentId": None,
            "message": "Appointment rescheduled, but could not confirm the new ID.",
        }
    except Exception as e:
        logger.exception(f"An unexpected error occurred in reschedule_appointment for appointmentId {appointment_id}.")
        return {"success": False, "message": f"An internal server error occurred: {e}"}


async def cancel_appointment(
    appointment_id: Annotated[str, Field(..., description="The unique ID of the appointment to cancel.")],
) -> Dict[str, Any]:
    """Cancels an existing appointment."""
    logger.info(f"Attempting to cancel appointment {appointment_id}")
    try:
        ctx = get_context()
        logger.info("Automatically fetching cancellation reasons.")
        params = {"$filter": "type eq 'as_cancel_reason'"}
        reasons_response = await make_api_request(ctx, "GET", "master/list-items", params=params)

        if not reasons_response.get("success"):
            logger.error(f"Could not fetch cancellation reasons. API response: {reasons_response}")
            return {"success": False, "message": "Could not fetch cancellation reasons."}

        reasons_data = reasons_response.get("message", {}).get("body", {}).get("items", [])

        # Search for the cancel reason by name instead of a fixed index.
        reason_id_to_use = None
        target_reason_name = "Appointment No Longer Needed"
        for reason in reasons_data:
            if reason.get("name") == target_reason_name:
                reason_id_to_use = reason.get("id")
                break

        if not reason_id_to_use:
            logger.error(f"Could not find a cancellation reason with the name '{target_reason_name}'.")
            return {"success": False, "message": f"A valid cancellation reason ('{target_reason_name}') could not be found."}

        logger.info(f"Automatically selected cancel reason ID: {reason_id_to_use}")

        payload = {"cancelReasonId": reason_id_to_use}
        endpoint = f"appointments/{appointment_id}/cancel"
        logger.debug(f"Making POST request to {endpoint} with payload: {payload}")
        response = await make_api_request(ctx, "POST", endpoint, json_data=payload)

        if not response.get("success"):
            logger.error(f"Failed to cancel appointment {appointment_id}. Response: {response}")
            return response

        logger.info(f"Successfully cancelled appointment {appointment_id}.")
        return {"success": True, "message": f"Appointment {appointment_id} canceled successfully."}
    except Exception as e:
        logger.exception(f"An unexpected error occurred in cancel_appointment for appointmentId {appointment_id}.")
        return {"success": False, "message": f"An internal server error occurred: {e}"}
