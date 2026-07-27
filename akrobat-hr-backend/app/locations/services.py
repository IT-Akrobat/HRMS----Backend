# from fastapi import HTTPException

# from app.core.database import supabase_admin


# def create_location(data):

#     try:

#         response = (
#             supabase_admin.table("locations")
#             .insert(
#                 {
#                     "location_name": data.location_name,
#                     "location_code": data.location_code,
#                     "address": data.address,
#                     "latitude": data.latitude,
#                     "longitude": data.longitude,
#                     "radius": data.radius,
#                 }
#             )
#             .execute()
#         )

#         return success_response(message=EMPLOYEE_CREATED, data=response.data[0])[0]

#     except Exception as e:

#         raise HTTPException(status_code=400, detail=str(e))


# def get_locations():

#     response = supabase_admin.table("locations").select("*").execute()

#     return success_response(message=EMPLOYEE_CREATED, data=response.data[0])


# def get_location(location_id: str):

#     response = (
#         supabase_admin.table("locations")
#         .select("*")
#         .eq("id", location_id)
#         .single()
#         .execute()
#     )

#     return success_response(message=EMPLOYEE_CREATED, data=response.data[0])


# def update_location(location_id: str, data: dict):

#     response = (
#         supabase_admin.table("locations").update(data).eq("id", location_id).execute()
#     )

#     return success_response(message=EMPLOYEE_CREATED, data=response.data[0])[0]


# def delete_location(location_id: str):

#     response = (
#         supabase_admin.table("locations").delete().eq("id", location_id).execute()
#     )

#     return {"message": "Location deleted successfully"}
from fastapi import HTTPException

from app.core.database import supabase_admin
from app.core.responses import success_response
from app.core.messages import EMPLOYEE_CREATED


def create_location(data):

    try:

        response = (
            supabase_admin.table("locations")
            .insert(
                {
                    "location_name": data.location_name,
                    "location_code": data.location_code,
                    "address": data.address,
                    "latitude": data.latitude,
                    "longitude": data.longitude,
                    "radius": data.radius,
                }
            )
            .execute()
        )

        return success_response(message=EMPLOYEE_CREATED, data=response.data[0])

    except Exception as e:

        raise HTTPException(status_code=400, detail=str(e))


def get_locations():

    response = supabase_admin.table("locations").select("*").execute()

    return success_response(
        message="Locations fetched successfully.", data=response.data
    )


def get_location(location_id: str):

    response = (
        supabase_admin.table("locations")
        .select("*")
        .eq("id", location_id)
        .single()
        .execute()
    )

    return success_response(
        message="Location fetched successfully.", data=response.data
    )


def update_location(location_id: str, data: dict):

    response = (
        supabase_admin.table("locations").update(data).eq("id", location_id).execute()
    )

    return success_response(
        message="Location updated successfully.", data=response.data[0]
    )


def delete_location(location_id: str):

    response = (
        supabase_admin.table("locations").delete().eq("id", location_id).execute()
    )

    return {"message": "Location deleted successfully"}
