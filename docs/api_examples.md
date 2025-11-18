API Examples
Events Endpoint
GET /eventsFetch events from NASA EONET API with optional parameters.
Example Request:
curl "http://localhost:8000/events?days=7&limit=100"

Example Response:
{
  "events": [
    {
      "id": "EONET_1234",
      "title": "Wildfire in Akmola",
      "categories": [{"id": "wildfires"}],
      "geometry": [{"type": "Point", "coordinates": [71.45, 51.16], "date": "2025-09-25"}]
    }
  ]
}

Sentinel Endpoint
GET /sentinelPlaceholder for Sentinel satellite data (not implemented).
Example Request:
curl "http://localhost:8000/sentinel"

Example Response:
{
  "message": "Sentinel endpoint not implemented yet"
}
