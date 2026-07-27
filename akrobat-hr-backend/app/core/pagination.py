def paginate(page: int = 1, limit: int = 20):

    page = max(page, 1)

    limit = max(min(limit, 100), 1)

    start = (page - 1) * limit

    end = start + limit - 1

    return start, end
