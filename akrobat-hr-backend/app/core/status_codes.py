from fastapi import status

# =============================
# SUCCESS
# =============================

HTTP_200_OK = status.HTTP_200_OK

HTTP_201_CREATED = status.HTTP_201_CREATED

HTTP_202_ACCEPTED = status.HTTP_202_ACCEPTED

HTTP_204_NO_CONTENT = status.HTTP_204_NO_CONTENT


# =============================
# CLIENT ERROR
# =============================

HTTP_400_BAD_REQUEST = status.HTTP_400_BAD_REQUEST

HTTP_401_UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED

HTTP_403_FORBIDDEN = status.HTTP_403_FORBIDDEN

HTTP_404_NOT_FOUND = status.HTTP_404_NOT_FOUND

HTTP_409_CONFLICT = status.HTTP_409_CONFLICT

HTTP_422_UNPROCESSABLE_ENTITY = status.HTTP_422_UNPROCESSABLE_CONTENT
# =============================
# SERVER ERROR
# =============================

HTTP_500_INTERNAL_SERVER_ERROR = status.HTTP_500_INTERNAL_SERVER_ERROR
