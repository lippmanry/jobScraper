#imports
from hdx.location.country import Country
from hdx.location.currency import Currency
import logging
import requests
from datetime import datetime, timezone, timedelta
from dateutil import parser
import re
import os
from dotenv import load_dotenv
import time
import math
from bs4 import BeautifulSoup

#inits
load_dotenv()
Currency.setup(fallback_historic_to_current=True, fallback_current_to_static=True, log_level=logging.INFO)

#const
base_url = 'https://ats-jobs-db.p.rapidapi.com/v1/jobs'
host = 'ats-jobs-db.p.rapidapi.com'
api_key = os.getenv('ATS_API_KEY')
webhook = os.getenv('DISCORD_WEBHOOK_URL')
ry_user = os.getenv('DISCORD_USER_ryan')
m_user = os.getenv('DISCORD_USER_mik')

#handle time limit argument
def max_posted_date(days_ago):
    if not days_ago:
        return None
    try:
        now = datetime.now(timezone.utc)
        midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        target_date = midnight_today - timedelta(days=int(days_ago))
        
        return target_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    except(ValueError,TypeError):
        return None
#handle posting time
def date_handler(posted_date):
    if not posted_date:
        return 'Not given', float('inf')
    try:
        posted_date = parser.isoparse(posted_date)
        
        if posted_date.tzinfo is None:
            posted_date = posted_date.replace(tzinfo=timezone.utc)
    
        current_date = datetime.now(timezone.utc)
        delta = current_date - posted_date
        total_seconds = delta.total_seconds()

        if total_seconds < 3600:
            #less than 1 hr
            minutes = int(total_seconds // 60)
            time_since = f"{minutes} min ago"
        elif total_seconds < 86400:
            #less than 1 day
            hours = int(total_seconds // 3600)
            time_since = f"{hours} hours ago"
        else:
            #more than 1 day
            time_since = f"{delta.days} days ago"
        

    except Exception as e:
        print(f"Error with date: {e}")
        return 'Unknown', float('inf')

    return time_since        

#format to USD for lazy americans like me
def format_usd(val, currency):
    if isinstance(val, (int, float)) and currency:
        try:
            usd_val = Currency.get_current_value_in_usd(val, currency)
            
            if usd_val is not None:
                return f'{usd_val:,.2f}'
        
        except Exception:
            pass
        
    return 'Not given'    

#compensation range
def compensation_handler(min_val, max_val, currency, is_usd=False):
    try:
        if is_usd:
            s_min = format_usd(min_val, currency)
            s_max = format_usd(max_val, currency)
            suffix = 'USD'
        else:
            s_min = f'{min_val:,.2f}' if isinstance(min_val, (int, float)) else 'Not given'
            s_max = f'{max_val:,.2f}' if isinstance(max_val, (int, float)) else 'Not given'
            suffix = currency
        
        if s_min == 'Not given' and s_max == 'Not given':
            return 'Not given'
        return f'{s_min} - {s_max} {suffix}'
    except (ValueError, TypeError, Exception):
        return 'Not given'

#use the country to change the currency instead of defaulting to USD
def get_currency(country_input):
    try:
        country_holder = Country.get_iso3_country_code_fuzzy(country_input)
        iso_code, is_valid = country_holder
        currency_code = Country.get_currency_from_iso3(iso_code)
        
        return currency_code if currency_code else 'USD'
    except Exception:
        pass


#if the salary is not an actual value
def salary_formatter(val):
    if isinstance(val, (int,float)):
        return f'{val:,.0f}'
    return str(val)

#use the country to change the currency instead of defaulting to USD
def get_currency(country_input):
    try:
        country_holder = Country.get_iso3_country_code_fuzzy(country_input)
        iso_code, is_valid = country_holder
        currency_code = Country.get_currency_from_iso3(iso_code)
        
        return currency_code if currency_code else 'USD'
    except Exception:
        pass

#deal with problematic salary range values
def parse_val(val, k_flag):
        clean_val = val.replace(',', '').strip('.')
        
        try:
            num = float(clean_val)
            if k_flag.lower() == 'k':
                num *= 1000
            return num
        except ValueError:
            return 0.0
#grab all ranges and list the lowest and highest for min and max instead of listing the first number twice
def fix_pay(html_desc, country_input):
    target_currency = get_currency(country_input)
    
    #make soups
    soup = BeautifulSoup(html_desc, 'html.parser')
    text_content = soup.get_text(separator=' ')
    #match all numbers in the ranges
    pattern = re.findall(r'\$\s*([\d,.]+)\s*([Kk]?)', text_content)
    
    all_values = [parse_val(n, k) for n, k in pattern]
    all_values = [v for v in all_values if 30000 < v < 1000000]
    if not all_values:
        return None
    
    
    min_pay = min(all_values)
    max_pay = max(all_values)
    
    return {
        'min': min_pay,
        'max': max_pay,
        'currency': target_currency
    }

#employment handler
def employment_handler(employment_type):
    if not employment_type: return 'Not given'
    t = employment_type.lower()
    try:    
        if 'full_time' in t: return 'Permanent'
            
        if 'contract' in t: return 'Contract'
            
        return 'Other'
    except Exception as e:
        return f'Error in employment_handler: {e}'


#cleanup html in description fields
def desc_cleanup(content):
    if not content or not isinstance(content, str):
        return 'Not given'
    try:
        soup = BeautifulSoup(content, 'html.parser')
        #we don't care about the headers for this. it's parsed elsewhere and could be a job or company description
        for junk in soup(['script', 'style','h1','h2','h3','h4','h5','h6']):
            junk.decompose()
            
        text = soup.get_text()
        words = text.split()
        lines = ' '.join(words)
        
        return lines if lines else 'Not given'
    except Exception as e:
        return f'Error parsing html description: {e}'

#sort functions
def sort_by_date(job_list, reverse=True):
    return sorted(job_list, key=lambda x: x.get('date_posted') or '', reverse=reverse)

def remote_only(job_list):
    return [job for job in job_list if job.get('is_remote') is True]

#discord notifications
def discord_notif(webhook_url, jobs, user_id=None, color=5814783):
    if not jobs:
        return
    seen_urls = set()
    unique_jobs = []
    for job in jobs:
        url = job.get('url')
        if url and url not in seen_urls:
            unique_jobs.append(job)
            seen_urls.add(url)
    
    #get 10 most recent
    newest_ten = sort_by_date(unique_jobs, reverse=True)[:10]
    #sort them so the newest are first seen in the scrolling chat
    sorted_jobs = newest_ten[::-1]
    
    mention = f'<@{user_id}> ' if user_id else ''
    
    header_data ={'content': f'{mention} **Your daily job report**: Newest {len(sorted_jobs)} new matches!'}
    response = requests.post(webhook_url, json=header_data)
    display_date = job['date_posted'][:10] if job['date_posted'] else "Not given"
    for i in range(0, len(sorted_jobs), 5):
        chunk = sorted_jobs[i:i + 5]
        embed_list = []
        for job in chunk:
            embed = {
                    "title": f"New Job: {job['job_title']}",
                    "url": job['url'],
                    "color": color,
                    "fields": [
                        {"name": "Company", "value": job['company'], "inline": True},
                        {"name": "Location", "value": job['location'], "inline": True},
                        {"name": "", "value": "\u200b", "inline": True}, #keeps row 1 separate
                        {"name": "Salary", "value": job['salary_range'], "inline": True},
                        {"name": "Salary in USD", "value": job['salary_range_usd'], "inline": True},
                        {"name": "", "value": "\u200b", "inline": True}, #keeps row 2 separate                    
                        {"name": "Remote", "value": "Yes" if job['is_remote'] else "No", "inline": True},
                        {"name": "Date posted", "value": display_date, "inline": True},                        
                        {"name": "Time since posted", "value": job['time_since_posted'], "inline": True}
                    ]
                }
            embed_list.append(embed)
            
        data = {
            'embeds': embed_list
        }
            
        response = requests.post(webhook_url, json=data)
        if response.status_code != 204:
                    print(f"Discord Error {response.status_code}: {response.text}")

        time.sleep(1)
#fetch jobs
def fetch_jobs(api_key=api_key, host=host,
            country = None,    
            max_pages_limit=100,
            q=None,
            results_per_page = 100,
            max_days_range=None,
            remote = None,
            **kwargs
            ):
    
    #headers
    headers = {
    'x-rapidapi-key': api_key,
    'x-rapidapi-host': host,
    'Content-type': 'application/json'
    }
    job_list = []
    
    current_page = 1
    total_pages = 1
    
    posted_after = max_posted_date(max_days_range)
    
    while current_page <= total_pages:
        #stop at user-defined limit:
        if current_page > max_pages_limit:
            print(f"Max pages limit was reached. Limit set at {max_pages_limit}.")
            break
        
        #params
        params = {
            'page_size': results_per_page,
            'location': country,
            'q': q,
            'page': current_page,
            'posted_after': posted_after,
            'remote': remote
        }
        params.update(kwargs)
        
        clean_params = {k: v for k, v in params.items() if v is not None and v != ""}
        
        try:

            response = requests.get(base_url, params=clean_params, headers=headers, timeout=10)
            #check response
            if response.status_code == 200:
                data = response.json()
                results = data.get('jobs', [])
            
                if not results:
                    break

                #get the total number of results and pages
                if current_page == 1:
                    total_count = data.get('total', 0)
                    total_pages = math.ceil(total_count / results_per_page)
                    actual_to_fetch = min(total_pages, max_pages_limit)
                    print(f"{total_count} jobs found on {total_pages} pages. Fetching {actual_to_fetch} pages based on user input limit.")
                
                page_items = []
                for job in results:
                            
                    locations = job.get('locations') or []
                    location_map = next(iter(locations), {})
                    #days since posted date handling
                    created_str = job.get('date_posted')
                    time_since = date_handler(created_str)
                    
                    comp = job.get('compensation') or {}
                    min_v = comp.get('min')
                    max_v = comp.get('max')
                    currency = comp.get('currency')
                    
                    if not min_v or not max_v:
                        pay = fix_pay(job.get('description'), country)
                        if pay:
                            
                            min_v = pay.get('min')
                            max_v = pay.get('max')
                            currency = pay.get('currency')

                    salary_range = compensation_handler(min_v, max_v, currency)
                    salary_range_usd = compensation_handler(min_v, max_v, currency, is_usd=True)
                    
                    emp_type_str = job.get('employment_type')
                    emp_type = employment_handler(emp_type_str)
                    desc = desc_cleanup(job.get('description'))
                    
                    
                    extracted_fields ={
                        'job_title': job.get('title', 'Not given'),
                        'company': job.get('company', {}).get('name'),
                        'location': location_map.get('location', 'Not given'),
                        'is_remote': job.get('is_remote'),
                        'date_posted': created_str,
                        'time_since_posted': time_since,
                        'experience': job.get('experience_level', 'Not given'),
                        'employment_type': emp_type,
                        'salary_range': salary_range,
                        'salary_range_usd': salary_range_usd,
                        'url': job.get('listing_url', 'Not given'),
                        'desc': desc
                    }
                    page_items.append(extracted_fields)

            
                job_list.extend(page_items)
                current_page += 1
                
            #too many datas, take a rest
            elif response.status_code == 429:
                print("Rate limit hit. Sleeping for 45s...")
                time.sleep(45)
                continue
            #something is messed up
            else:
                print(f"Error response status {response.status_code}: {response.text}")
                break
        #oh nooooo what happened??
        except Exception as e:
            print(f"An error has occurred: {e}")
            break
        
    return job_list