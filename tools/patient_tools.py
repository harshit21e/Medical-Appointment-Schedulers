from pydantic import Field
from typing import Dict, Any, Optional, Annotated
from ..utils import make_api_request
from utils.log_utils import setup_logger
from fastmcp.server.dependencies import get_context

logger = setup_logger(__name__)


async def get_patient(
    first_name: Annotated[str, Field(..., description="The patient's first name.")],
    last_name: Annotated[str, Field(..., description="The patient's last name.")],
    birth_date: Annotated[str, Field(..., description="The patient's date of birth in YYYY-MM-DD format.")],
    phone_number: Annotated[
        Optional[str],
        Field(
            None,
            description="The patient's phone number. Used to find a unique match if multiple patients share the same name and birth date.",
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Finds an existing patient using their name, date of birth, and optionally a phone number.
    """
    ctx = get_context()
    logger.info(f"Attempting to find patient: {first_name} {last_name}, DOB: {birth_date}")

    search_params = {
        "firstName": first_name,
        "lastName": last_name,
        "dateOfBirth": birth_date,
        "excludeExpired": "false",
    }
    if phone_number:
        search_params["phone"] = phone_number

    search_response = await make_api_request(ctx, "GET", "persons/lookup", params=search_params)

    if not search_response.get("success"):
        return search_response

    response_data = search_response.get("message", {}).get("body", {})
    patients = []

    if isinstance(response_data, dict) and "items" in response_data:
        patients = response_data.get("items", [])
    elif isinstance(response_data, list):
        patients = response_data

    if len(patients) == 1:
        person_id = patients[0].get("id")
        logger.info(f"Found unique patient with ID: {person_id}")
        return {"success": True, "personId": person_id, "message": "Patient found successfully."}

    if len(patients) > 1:
        logger.warning("Multiple patients found.")
        return {
            "success": False,
            "personId": None,
            "message": "Multiple patients found. Please ask for a phone number to confirm.",
        }

    logger.info("No patient found with the provided details.")
    return {"success": False, "personId": None, "message": "Patient not found."}


async def create_patient(
    first_name: Annotated[str, Field(..., description="The patient's first name.")],
    last_name: Annotated[str, Field(..., description="The patient's last name.")],
    birth_date: Annotated[str, Field(..., description="The patient's date of birth in YYYY-MM-DD format.")],
    sex: Annotated[
        str, Field(..., description="The patient's sex at birth. Use 'M' for male, 'F' for female, or 'U' for unknown.")
    ],
    phone_number: Annotated[str, Field(..., description="The patient's home phone number.")],
    email_address: Annotated[str, Field(..., description="The patient's email address.")],
    ignore_duplicates: Annotated[
        Optional[bool],
        Field(
            False, description="Set to true to bypass the duplicate patient check if the system flags a potential duplicate."
        ),
    ] = False,
) -> Dict[str, Any]:
    """
    Creates a new patient record.
    """
    ctx = get_context()
    logger.info(f"Attempting to create a new patient: {first_name} {last_name}")

    create_payload = {
        "firstName": first_name,
        "lastName": last_name,
        "dateOfBirth": f"{birth_date}T00:00:00",
        "sex": sex,
        "homePhone": phone_number,
        "emailAddress": email_address,
    }

    if ignore_duplicates:
        create_payload["ignoreDuplicatePersons"] = True

    create_response = await make_api_request(ctx, "POST", "persons", json_data=create_payload)

    if not create_response.get("success"):
        return create_response

    headers = create_response.get("message", {}).get("headers", {})
    location_header = headers.get("location") or headers.get("Location")

    if not location_header:
        logger.error("Could not find Location header in the response after creating a patient.")
        return {"success": False, "personId": None, "message": "Patient was created, but the new ID could not be retrieved."}

    try:
        new_person_id = location_header.split("/")[-1]
        if not new_person_id:
            raise ValueError("Parsed person ID from Location header is empty.")

        logger.info(f"Successfully created new patient '{first_name} {last_name}' with ID: {new_person_id}")

        return {"success": True, "personId": new_person_id, "message": "New patient created successfully."}
    except (IndexError, ValueError) as e:
        logger.error(f"Could not parse personId from Location header: '{location_header}'. Error: {e}")
        return {"success": False, "personId": None, "message": "Patient was created, but failed to parse the new ID."}
