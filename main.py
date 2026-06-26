# ============================================
# Party Planner API
# Author: Nayla Hanegan (naylahanegan@gmail.com)
# Date: 7/21/2024
# License: MIT
# ============================================

from bs4 import BeautifulSoup
from datetime import datetime
from fastapi import FastAPI, Query, Path, Response as FastAPIResponse, Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlparse, urlsplit, urlunsplit, quote, parse_qs
import re
import requests

app = FastAPI(title='PartyPlanner64 API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://mariopartylegacy.com"

def resolve_download_files(download_href: str):
    full_url = BASE_URL + download_href if download_href.startswith('/') else download_href

    try:
        response = requests.head(full_url, allow_redirects=True)
        content_disposition = response.headers.get('Content-Disposition')
        if content_disposition:
            filename = content_disposition.split('filename=')[-1].strip('"')
            return [{"file_name": filename, "download_link": response.url}]
        if 'text/html' not in response.headers.get('Content-Type', ''):
            return [{"file_name": "Filename not found", "download_link": full_url}]
    except requests.RequestException:
        pass

    try:
        response = requests.get(full_url, allow_redirects=True)
        content_disposition = response.headers.get('Content-Disposition')
        if content_disposition:
            filename = content_disposition.split('filename=')[-1].strip('"')
            return [{"file_name": filename, "download_link": response.url}]

        soup = BeautifulSoup(response.text, 'html.parser')
        files = []
        for row in soup.select('.contentRow'):
            title = row.select_one('h3.contentRow-title')
            link = row.select_one('a.button--icon--download')
            size = row.select_one('.contentRow-minor')
            if not title or not link or not link.get('href'):
                continue
            file_info = {
                "file_name": title.get_text(strip=True),
                "download_link": BASE_URL + link['href'],
            }
            if size:
                file_info["file_size"] = size.get_text(strip=True)
            sub_file_id = parse_qs(urlparse(link['href']).query).get('file')
            if sub_file_id:
                file_info["sub_file_id"] = sub_file_id[0]
            files.append(file_info)
        if files:
            return files
    except requests.RequestException:
        pass

    return [{"file_name": "Filename not found", "download_link": full_url}]

def fetch_files(id: int, file_id: int = None):
    url = f"https://mariopartylegacy.com/forum/downloads/{id}/history"
    response = requests.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    versions = []

    for row in soup.select('.dataList-row'):
        version_info = {}
        cells = row.select('.dataList-cell')

        if cells:
            version_info["file_version"] = cells[0].get_text(strip=True)

            american_date = cells[1].get_text(strip=True)
            try:
                international_date = datetime.strptime(american_date, '%b %d, %Y').strftime('%Y-%m-%d')
            except ValueError:
                international_date = None
            version_info["release_date"] = international_date

            version_info["download_count"] = cells[2].get_text(strip=True)

            rating_text = cells[3].get_text(strip=True)
            try:
                rating_parts = rating_text.split(' ')
                score = float(rating_parts[0])
                stars = score * 0.05 * 400
                formatted_stars = str(int(stars)) if stars.is_integer() else f"{stars:.2f}"
                version_info["rating"] = formatted_stars
            except (IndexError, ValueError):
                version_info["rating"] = rating_text

            link = cells[4].select_one('a')
            if link and link['href']:
                version_info["download_link"] = BASE_URL + link['href']

                path = urlparse(version_info["download_link"]).path
                parts = path.split('/')
                if len(parts) > 3:
                    version_id = parts[3].split('.')[1]
                    version_info["file_id"] = version_id

                download_files = resolve_download_files(link['href'])
                if len(download_files) == 1:
                    version_info["file_name"] = download_files[0]["file_name"]
                    version_info["download_link"] = download_files[0]["download_link"]
                else:
                    version_info["files"] = download_files
                    version_info["file_name"] = ", ".join(f["file_name"] for f in download_files)

            versions.append(version_info)

    # Exclude the first entry
    versions = versions[1:]

    # Filter by file_id if provided
    if file_id:
        versions = [version for version in versions if version.get("file_id") == str(file_id)]

    return versions

def search_projects(term: str, gameId: int = None):
    # URL encode the search term
    encoded_term = quote(term)
    
    # Construct the URL with the encoded search term
    url = f"https://www.mariopartylegacy.com/forum/search/search?search_type=resource&keywords={encoded_term}&t=resource&c[categories][0]=1&c[nodes]=1&c[title_only]=1&o=date"
    
    # Send the HTTP request
    response = requests.get(url)
    response.raise_for_status()
    
    # Parse the HTML response
    soup = BeautifulSoup(response.text, 'html.parser')

    results = []

    # Iterate over each <h3> tag with class 'contentRow-title'
    for content in soup.find_all('h3', class_='contentRow-title'):
        # Find the <a> tag within <h3>
        link_tag = content.find('a')
        if link_tag and 'href' in link_tag.attrs:
            href = link_tag['href']
            print("Full href:", href)  # Debugging line
            
            # Update the regex pattern to capture the number after the dot
            project_id_match = re.search(r'/downloads/[^.]+(?:\.(\d+))/', href)
            if project_id_match:
                project_id_str = project_id_match.group(1)
                try:
                    project_id = int(project_id_str)
                except ValueError:
                    continue  # Skip if project_id is not a valid integer
            else:
                continue  # Skip if project_id cannot be extracted
            
            # Extract title and prefix
            title_text = link_tag.text.strip()
            name = None
            extracted_gameId = None

            # Extract the prefix and name
            for prefix in ["MP1", "MP2", "MP3"]:
                if title_text.startswith(prefix):
                    name = title_text[len(prefix):].split('\n')[0].strip()
                    extracted_gameId = int(prefix.strip()[2:])
                    
                    # Check if the extracted_gameId matches the provided gameId
                    if gameId is None or extracted_gameId == gameId:
                        project_info = {
                            "name": name,
                            "gameId": extracted_gameId,
                            "projectId": project_id
                        }
                        results.append(project_info)

    return results

def fetch_project(id: int):
    url = f"https://mariopartylegacy.com/forum/downloads/{id}/"
    response = requests.get(url)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    project_info = {"id": id}

    # Extract the h1 element with class 'p-title-value'
    content = soup.find('h1', class_='p-title-value')
    if content:
        title_text = content.text.strip()
        for prefix in ["MP1 ", "MP2 ", "MP3 "]:
            if title_text.startswith(prefix):
                project_info["name"] = title_text[len(prefix):]
                project_info["gameId"] = int(prefix.strip())
                break

    # Extract additional project info
    content = soup.find('a', class_='username u-concealed')
    if content:
        project_info["author"] = content.text.strip()

    content = soup.find('time', class_='u-dt')
    if content:
        american_date = content.text.strip()
        try:
            international_date = datetime.strptime(american_date, '%b %d, %Y').strftime('%Y-%m-%d')
        except ValueError:
            international_date = None
        project_info["creation_date"] = international_date

    try:
        board_difficulty = soup.find('dl', {'data-field': 'board_difficulty'}).find('dd').get_text(strip=True)
        difficulty_mapping = {
            "Beginner": 1,
            "Average": 2,
            "Challenging": 3,
            "Complex": 4,
            "Extreme": 5
        }
        project_info["difficulty"] = difficulty_mapping.get(board_difficulty, -1)
    except AttributeError:
        project_info["difficulty"] = -1

    try:
        recommended_turns = soup.find('dl', {'data-field': 'board_turns'}).find('dd').get_text(strip=True)
        project_info["recommended_turns"] = int(recommended_turns)
    except (AttributeError, ValueError):
        project_info["recommended_turns"] = -1

    try:
        custom_events = soup.find('dl', {'data-field': 'board_events'}).find('dd').get_text(strip=True)
        event_mapping = {
            "No": 0,
            "Yes (Unique)": 2,
            "Yes": 1
        }
        project_info["custom_events"] = event_mapping.get(custom_events, -1)
    except AttributeError:
        project_info["custom_events"] = -1

    try:
        custom_music = soup.find('dl', {'data-field': 'board_music'}).find('dd').get_text(strip=True)
        music_mapping = {
            "No": 0,
            "Yes": 1
        }
        project_info["custom_music"] = music_mapping.get(custom_music, -1)
    except AttributeError:
        project_info["custom_music"] = -1
    
    try:
        playable_on_n64 = soup.find('dl', {'data-field': 'board_hardware'}).find('dd').get_text(strip=True)
        hardware_mapping = {
            "No": 0,
            "Yes": 1,
            "Untested": 2
        }
        project_info["playable_on_n64"] = hardware_mapping.get(playable_on_n64, -1)
    except AttributeError:
        project_info["playable_on_n64"] = -1

    try:
        space_count = soup.find('dl', {'data-field': 'board_spaces'}).find('dd').get_text(strip=True)
        project_info["space_count"] = int(space_count)
    except (AttributeError, ValueError):
        project_info["space_count"] = -1
    
    try:
        theme = soup.find('dl', {'data-field': 'board_theme'}).find('dd').get_text(strip=True)
        project_info["theme"] = theme
    except AttributeError:
        pass

    content = soup.find('div', class_='bbWrapper')
    if content:
        description = ' '.join(content.text.splitlines())
        match = re.search(r'(.*?)   Spoiler\s*(.*?)\s*   (.*)', description, re.DOTALL)
        if match:
            description = match.group(1).strip() + " " + match.group(3).strip()
        project_info["description"] = description

    content_row_figure = soup.find_all('div', class_='contentRow contentRow--hideFigureNarrow')
    for figure in content_row_figure:
        avatar_div = figure.find('span', class_='contentRow-figure')
        if avatar_div:
            img_tag = avatar_div.find('img')
            if img_tag and 'src' in img_tag.attrs:
                project_info["icon"] = "https://mariopartylegacy.com" + img_tag['src']

    return project_info

@app.get("/project/search")
async def search_for_projects(
    searchTerm: str = Query(None, description="The string to search for"), 
    gameId: int = Query(None, description="The ID of the game to filter by")):
    projects = search_projects(searchTerm, gameId)
    if projects:
        return projects
    else:
        return {"error": "No results"}

@app.get("/project/top")
async def get_top_boards(max: int = Query(50, description="Maximum number of boards to return")):
    boards = []
    page = 1
    safety_limit = 100
    while len(boards) < max and page <= safety_limit:
        url = f"https://www.mariopartylegacy.com/forum/downloads/categories/boards.1/?page={page}"
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        found = False
        for item in soup.find_all('div', class_='structItem--resource'):
            found = True
            board = {}
            title_tag = item.find('div', class_='structItem-title').find('a')
            if title_tag:
                board['name'] = title_tag.text.strip()
                board['link'] = 'https://www.mariopartylegacy.com' + title_tag['href']
                # Extract id from the link, e.g. /forum/downloads/board-name.123/ -> 123
                match = re.search(r'\.(\d+)/', title_tag['href'])
                if match:
                    board['id'] = int(match.group(1))
            creator_tag = item.find('a', class_='username')
            if creator_tag:
                board['creator'] = creator_tag.text.strip()
            meta = item.find_all('dl', class_='pairs pairs--justified')
            for pair in meta:
                dt = pair.find('dt')
                dd = pair.find('dd')
                if not dt or not dd:
                    continue
                label = dt.text.strip().lower()
                value = dd.text.strip()
                if 'downloads' in label:
                    board['downloads'] = value
                elif 'views' in label:
                    board['views'] = value
                elif 'version' in label:
                    board['version'] = value
                elif 'updated' in label:
                    board['updated'] = value
            boards.append(board)
            if len(boards) >= max:
                break
        if not found or len(boards) >= max:
            break
        page += 1
    return boards[:max]

@app.get("/project/{projectId}")
async def get_project_info(projectId: int = Path(..., description="The Project ID of the project to lookup.")):
    project = fetch_project(projectId)
    if project:
        return project
    else:
        return {"error": "Project not found"}

@app.get("/project/{projectId}/files")
async def get_project_files(projectId: int = Path(..., description="The Project ID of the project to lookup.")):
    versions = fetch_files(projectId)
    if versions:
        return {"projectId": projectId, "versions": versions}
    else:
        return {"error": "Files not found"}

@app.get("/project/{projectId}/files/{fileId}")
async def get_project_file_info(projectId: int = Path(..., description="The Project ID of the project to lookup."), fileId: int = Path(..., description="The File ID of the project to lookup.")):
    versions = fetch_files(projectId, file_id=fileId)
    if versions:
        return versions[0]
    else:
        return {"error": "File not found"}

@app.get("/cors_bypass")
async def cors_bypass(url: str = Query(..., description="The URL to fetch via the CORS proxy")):
    try:
        r = requests.get(url, stream=True)
        headers = dict(r.headers)
        # Set CORS headers
        headers['Access-Control-Allow-Origin'] = '*'
        headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return FastAPIResponse(
            content=r.content,
            status_code=r.status_code,
            headers=headers
        )
    except Exception as e:
        return FastAPIResponse(f'Error: {str(e)}', status_code=500)
   
