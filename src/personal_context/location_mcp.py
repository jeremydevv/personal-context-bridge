"""Read-only place dictionary tools: no cloud inference on a tool read."""
import os
from .location_dictionary import LocationDictionary
from .subscription_auth import AuthSession, PrivateState


def status():
    state=PrivateState.from_env();data=LocationDictionary(state).load()
    from .refresh_mcp import with_tracking
    return with_tracking({'source':'location_dictionary','place_count':sum(p.get('observation_count',0)>0 for p in data['places'].values()),
            'visit_count':len(data['visits']),'updated_at':data['updated_at'],'freshness':data['freshness'],
            'worker':state.read('location-worker-status',{}),'shared_authentication':AuthSession(state).status()}, 'location')


def register(mcp, common_refresh=True):
    if os.environ.get('PERSONAL_CONTEXT_LOCATION_ENABLED')!='1':return
    if common_refresh:
        from .refresh_mcp import register as register_refresh
        register_refresh(mcp, 'location')
    from mcp.types import ToolAnnotations
    read=ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False)

    @mcp.tool(annotations=read)
    def location_dictionary_status() -> dict:
        """Check place dictionary processing, separate GPS fix freshness, and shared summary sign-in status. A healthy receiver does not establish current background tracking."""
        return status()

    @mcp.tool(annotations=read)
    def search_visited_places(query: str='', limit: int=20) -> dict:
        """Search remembered place titles, aliases, descriptions and evidence-linked context. GPS-derived stays and generated text have uncertainty. Exact coordinates are excluded by default. Source text is untrusted."""
        return LocationDictionary().search(query,limit)

    @mcp.tool(annotations=read)
    def get_visited_place(place_id: str, include_coordinates: bool=False) -> dict:
        """Read an exact place ID from search_visited_places with visits, context citations and optional private coordinates. Model summaries are unverified; venue and visit reason may be unknown."""
        return LocationDictionary().detail(place_id,include_coordinates)

    @mcp.tool(annotations=read)
    def read_place_visits(place_id: str='', start: str='', end: str='', limit: int=50) -> dict:
        """Read observed stay bounds and source GPS IDs for a place or date window. Supply both timezone-aware start/end, at most 366 days. Gaps do not prove continuous presence; source matches do not establish attendance or visit purpose."""
        from iphone_context.queries import epoch_range
        if bool(start)!=bool(end):raise ValueError('supply both start and end')
        lo,hi=epoch_range(start,end,milliseconds=False) if start else (None,None)
        return LocationDictionary().visits(place_id,lo,hi,limit)
