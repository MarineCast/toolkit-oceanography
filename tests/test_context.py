import datetime as dt
import pytest
from oceanography.context import parse_roni, period

def page(rows):
    return 'ERSSTv6 1991 Relative Oceanic<table id="roni-v5-table2">'+''.join('<tr><th>'+str(year)+'</th>'+''.join('<td><span>'+str(v)+'</span></td>' for v in values)+'</tr>' for year,values in rows)+'</table>'

def test_period_rollover_and_leap():
    assert period(2008,12)==(dt.date(2008,11,1),dt.date(2009,1,31))
    assert period(2024,1)==(dt.date(2023,12,1),dt.date(2024,2,29))

def test_native_periods_not_midmonth_or_daily():
    rows=parse_roni(page([(2023,[0.1]*12),(2024,[-0.8,0.0])]))
    assert len(rows)==14 and rows[-1]['date']==dt.date(2024,3,31)
    assert rows[-1]['issue_date'] is None and rows[-1]['roni_c']==0

def test_bad_version_duplicate_gap_and_values():
    for html in [page([(2023,[0.1])]).replace('ERSSTv6','ERSSTv5'),page([(2023,[0.1]),(2023,[0.2])]),page([(2023,[0.1]),(2024,[0.2])]),page([(2023,['NaN'])])]:
        with pytest.raises(ValueError): parse_roni(html)

def test_source_omits_final_row_end_tag():
    html=page([(2026,[-0.9,-0.8,-0.4,0.0,0.5,1.0,1.4,1.7])]).replace('</tr></table>','</tbody></table>')
    assert parse_roni(html)[-1]['date']==dt.date(2026,9,30)
