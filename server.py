import os
from fastmcp import FastMCP
from .tools.patient_tools import get_patient, create_patient
from .tools.appointment_tools import (
    get_appointment_categories,
    get_category_events,
    get_available_slots,
    get_patient_appointments,
    book_appointment,
    reschedule_appointment,
    cancel_appointment,
)

# Initialize the FastMCP server
mcp = FastMCP(name="NextGen MCP Server", stateless_http=False)


def load_markdown_prompt(prompt_name: str) -> str:
    """Helper function to load a system prompt from the /prompts directory."""
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", f"{prompt_name}.md")
    try:
        with open(prompt_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"Prompt file not found: {prompt_path}"


@mcp.prompt()
def appointment_assistant_prompt() -> str:
    """Loads and sets the main system prompt for the appointment booking assistant."""
    return load_markdown_prompt("appointment_prompt")


mcp.tool(
    description="""
    Finds an existing patient using their first name, last name, and date of birth.
    Use this tool first to check if a patient is already in the system.
    If multiple patients are found, it will return a message asking for a phone number to clarify.
    If no patient is found, you must then use the 'create_patient' tool.
    """
)(get_patient)

mcp.tool(
    description="""
    Creates a new patient record. Use this tool ONLY after the 'get_patient' tool
    fails to find an existing patient. It requires the patient's first name, last name,
    date of birth, sex, phone number, and email.
    """
)(create_patient)


mcp.tool(
    description="""
    Gets the master list of all appointment categories, such as 'New Patient Visit' or 'Follow-Up'.
    Use this tool after a patient has been identified to determine the reason for their visit.
    Use the returned list to ask the user for the general type of appointment they need.
    """
)(get_appointment_categories)

mcp.tool(
    description="""
    After the user has selected a category, use this tool with the categoryId to get the list
    of specific reasons for the visit (events), like 'Annual Physical' or 'Consultation'.
    The user must choose one of these events.
    """
)(get_category_events)

mcp.tool(
    description="""
    After the user provides a category and a preferred date, use this tool to find available appointment slots.
    It requires the category ID and the desired date (in YYYY-MM-DD format).
    The response includes location, provider (resource), and the exact time for each available slot.
    """
)(get_available_slots)

mcp.tool(
    description="""
    After finding a patient's personId, use this tool to retrieve a list of their upcoming appointments.
    This is a required first step before you can cancel or reschedule an appointment,
    as you need the specific appointmentId and other details from this list.
    """
)(get_patient_appointments)

mcp.tool(
    description="""
    Books the final appointment. This is the last step. This tool requires ALL of the following collected information:
    - The 'personId' from the 'get_patient' tool.
    - The 'eventId' from the specific event chosen after using the 'get_category_events' tool. DO NOT use any other ID for this parameter.
    - The 'locationId', 'resourceId', 'appointmentDate', and 'durationMinutes' that were all provided in the specific time slot selected by the patient from the 'get_available_slots' tool.
    """
)(book_appointment)

mcp.tool(
    description="""
    Updates (reschedules) an existing appointment to a new time slot. This action requires
    the original appointmentId and all details for the NEW appointment. The reason is handled automatically.
    """
)(reschedule_appointment)

mcp.tool(
    description="""
    Cancels an existing appointment using its unique appointmentId. The reason is handled automatically.
    """
)(cancel_appointment)
