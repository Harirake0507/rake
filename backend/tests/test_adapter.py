from app import bms_adapter as b

SAMPLE = '''
<html><body>
AVAILABLE FAST FILLING
<h3>Baththa (UA13+)</h3><div>Tamil, 2D</div><div>10:30 AM</div><div>07:30 PM</div>
<h3>Meesaya Murukku 2 (UA13+)</h3><div>Tamil, 2D</div><div>08:15 PM</div>
</body></html>
'''

def test_showtime_parser_associates_movies(monkeypatch):
    monkeypatch.setattr(b, '_get', lambda *args, **kwargs: SAMPLE)
    cinema = {'name': 'MAYAJAAL', 'showtimes_url': 'https://in.bookmyshow.com/cinemas/chennai/x/buytickets/X/20261008'}
    data = b.showtimes_for_cinema(cinema)
    assert len(data['shows']) == 3
    assert data['shows'][0]['movie'] == 'Baththa (UA13+)'
    assert data['shows'][2]['movie'] == 'Meesaya Murukku 2 (UA13+)'

def test_check_alert_never_matches_unknown_movie(monkeypatch):
    monkeypatch.setattr(b, 'cinemas', lambda city: [{'name':'Test Cinema','id':'test','showtimes_url':'x'}])
    monkeypatch.setattr(b, 'showtimes_for_cinema', lambda *args, **kwargs: {
        'cinema':'Test Cinema','source_url':'x','shows':[{'movie':None,'time':'07:30 PM','status':'AVAILABLE','booking_url':'x'}]
    })
    result = b.check_alert('Baththa', ['Test Cinema'])
    assert result[0]['matches'] == []

def test_check_alert_matches_case_insensitively(monkeypatch):
    monkeypatch.setattr(b, 'cinemas', lambda city: [{'name':'Test Cinema','id':'test','showtimes_url':'x'}])
    monkeypatch.setattr(b, 'showtimes_for_cinema', lambda *args, **kwargs: {
        'cinema':'Test Cinema','source_url':'x','shows':[{'movie':'Baththa (UA13+)','time':'07:30 PM','status':'AVAILABLE','booking_url':'x'}]
    })
    result = b.check_alert('baththa', ['Test Cinema'], available_only=True)
    assert len(result[0]['matches']) == 1
