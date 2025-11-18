"""
/backend/biopar_sentinelhub.py — BIOPAR (LAI, FAPAR, FCOVER) через Sentinel Hub Processing API.

Улучшенная версия с:
- Правильными evalscript V3 на основе SNAP NN (Sentinel Hub Custom Scripts)
- Жёсткой маской облаков по SCL (3, 8, 9, 10, 11) + dataMask
- Улучшенным кэшированием и обработкой ошибок
- Детальным логированием и retry-логикой
- Валидацией входных параметров
- Сохранением метаданных запросов

Особенности:
- Токен CDSE по client_credentials (как в ndvi_sentinelhub.py)
- Evalscript V3 для LAI/FAPAR/FCOVER на основе SNAP NN алгоритмов
- Унифицированные исключения и retry-логика
- Поддержка harmonization для Sentinel-2 временных рядов

Требования:
- python-dotenv, requests
- .env с CDSE_CLIENT_ID и CDSE_CLIENT_SECRET

Ограничения:
- Поддерживаются биопараметры: 'LAI', 'FAPAR', 'FCOVER'.
- Для 'CCC' и 'CWC' поднято NotImplementedError (используй openEO в backend/biopar.py).
"""

import logging
import os
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
import hashlib
import json
import requests
from enum import Enum

logger = logging.getLogger(__name__)

# Импорт настроек для exponential backoff
from backend.settings import settings

# Загрузка .env
env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)


def _calculate_retry_delay(attempt: int, base_delay: float, backoff_factor: float) -> float:
    """
    Вычисляет задержку с экспоненциальным отступом.

    Args:
        attempt: Номер попытки (0-based)
        base_delay: Базовая задержка в секундах
        backoff_factor: Коэффициент экспоненциального роста

    Returns:
        Задержка в секундах с экспоненциальным отступом
    """
    return base_delay * (backoff_factor ** attempt)

# Директория кэша
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "biopar_sh"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# CDSE credentials
CDSE_CLIENT_ID = os.getenv("CDSE_CLIENT_ID")
CDSE_CLIENT_SECRET = os.getenv("CDSE_CLIENT_SECRET")

if not CDSE_CLIENT_ID or not CDSE_CLIENT_SECRET:
    logger.error("CDSE credentials not loaded from .env!")
else:
    logger.info(f"CDSE credentials loaded: {CDSE_CLIENT_ID[:10]}...")

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Версия evalscript для кэш-инвалидации
EVALSCRIPT_VERSION = "biopar-v2.0"


class MosaickingOrder(str, Enum):
    """Типы упорядочивания мозаики согласно Sentinel Hub API."""
    MOST_RECENT = "mostRecent"
    LEAST_RECENT = "leastRecent"
    LEAST_CC = "leastCC"  # Наименьшая облачность


class SentinelHubError(Exception):
    """Базовая ошибка Sentinel Hub API."""
    pass


class NoDataAvailableError(SentinelHubError):
    """Нет данных для запрошенного периода/области."""
    pass


class AuthenticationError(SentinelHubError):
    """Ошибка аутентификации."""
    pass


# ---------------------- Аутентификация ---------------------- #

def get_cdse_token() -> str:
    """
    Получить OAuth2 токен для Copernicus Data Space Ecosystem.
    
    Returns:
        str: Access token
        
    Raises:
        AuthenticationError: При ошибке аутентификации
    """
    try:
        logger.info(f"Requesting token for client: {CDSE_CLIENT_ID[:10]}...")
        
        resp = requests.post(
            CDSE_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": CDSE_CLIENT_ID,
                "client_secret": CDSE_CLIENT_SECRET,
            },
            timeout=30,
        )
        
        logger.info(f"Token response status: {resp.status_code}")
        
        if resp.status_code != 200:
            error_msg = f"Authentication failed: {resp.text}"
            logger.error(error_msg)
            raise AuthenticationError(error_msg)
            
        token = resp.json()["access_token"]
        logger.info("Token obtained successfully")
        return token
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during authentication: {e}", exc_info=True)
        raise AuthenticationError(f"Network error: {e}")
    except KeyError as e:
        logger.error(f"Invalid token response format: {e}", exc_info=True)
        raise AuthenticationError("Invalid token response format")
    except Exception as e:
        logger.error(f"Unexpected auth error: {e}", exc_info=True)
        raise AuthenticationError(f"Unexpected error: {e}")


# ---------------------- Evalscripts (V3) ---------------------- #

def _wrap_with_cloudmask(core_setup: str, core_eval: str, use_cloud_mask: bool, mosaicking: str) -> str:
    """
    Встраивает cloudmask (SCL + dataMask) поверх базового evalscript.
    
    Args:
        core_setup: Базовая функция setup()
        core_eval: Базовая функция evaluatePixel()
        use_cloud_mask: Использовать облачную маску
        mosaicking: Тип мозаики
        
    Returns:
        str: Полный evalscript V3 с маскированием
        
    Notes:
        Ожидается, что core_eval определяет функцию evaluatePixelOrig(sample, scene, ...),
        возвращающую объект/массив с 1 каналом.
    """
    scl_mask_block = """
  // Проверка dataMask
  if (sample.dataMask === 0) return [NaN];
  
  // Маска облаков по Scene Classification Layer
  // 3=Cloud shadow, 8=Cloud medium probability, 9=Cloud high probability,
  // 10=Thin cirrus, 11=Snow/Ice
  if (sample.SCL === 3 || sample.SCL === 8 || sample.SCL === 9 || 
      sample.SCL === 10 || sample.SCL === 11) {
    return [NaN];
  }
""" if use_cloud_mask else """
  // Проверка dataMask
  if (sample.dataMask === 0) return [NaN];
"""

    return f"""//VERSION=3
function setup() {{
  const base = {core_setup.strip()};
  // Добавляем служебные слои для маски
  const bands = new Set(base.input[0].bands);
  bands.add("dataMask");
  {"bands.add('SCL');" if use_cloud_mask else ""}
  base.input[0].bands = Array.from(bands);
  base.mosaicking = "{mosaicking}";
  // Гарантируем числовой выход FLOAT32
  base.output = [{{id:"default", bands:1, sampleType:"FLOAT32"}}];
  return base;
}}

{core_eval}

function evaluatePixel(sample, scene, metadata, customData, outputMetadata) {{
{scl_mask_block}
  // Делегируем вычисление в оригинальный скрипт
  const res = evaluatePixelOrig([sample], scene, metadata, customData, outputMetadata);
  // res может быть объектом вида {{default:[val]}} или массивом
  if (Array.isArray(res)) return res;
  const key = Object.keys(res)[0];
  return res[key];
}}
"""


def _evalscript_fapar() -> str:
    """
    Evalscript для FAPAR (Fraction of Absorbed PAR).
    Основан на SNAP NN алгоритме из Sentinel Hub Custom Scripts.
    
    Returns:
        str: Evalscript V3 код с облачной маской
    """
    core_setup = """
{
  input: [{
    bands: ["B03","B04","B05","B06","B07","B8A","B11","B12",
            "viewZenithMean","viewAzimuthMean","sunZenithAngles","sunAzimuthAngles"]
  }],
  output: [{id:"default", bands:1, sampleType:"AUTO"}]
}
"""
    core_eval = r"""
var degToRad = Math.PI / 180;

function evaluatePixelOrig(samples) {
  var sample = samples[0];
  
  // Нормализация входных данных
  var b03_norm = normalize(sample.B03, 0, 0.253061520471542);
  var b04_norm = normalize(sample.B04, 0, 0.290393577911328);
  var b05_norm = normalize(sample.B05, 0, 0.305398915248555);
  var b06_norm = normalize(sample.B06, 0.006637972542253, 0.608900395797889);
  var b07_norm = normalize(sample.B07, 0.013972727018939, 0.753827384322927);
  var b8a_norm = normalize(sample.B8A, 0.026690138082061, 0.782011770669178);
  var b11_norm = normalize(sample.B11, 0.016388074192258, 0.493761397883092);
  var b12_norm = normalize(sample.B12, 0, 0.493025984460231);
  
  var viewZen_norm = normalize(Math.cos(sample.viewZenithMean * degToRad), 0.918595400582046, 1);
  var sunZen_norm  = normalize(Math.cos(sample.sunZenithAngles * degToRad), 0.342022871159208, 0.936206429175402);
  var relAzim_norm = Math.cos((sample.sunAzimuthAngles - sample.viewAzimuthMean) * degToRad);
  
  // Нейронная сеть (5 нейронов скрытого слоя)
  var n1 = neuron1(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n2 = neuron2(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n3 = neuron3(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n4 = neuron4(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n5 = neuron5(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  
  var l2 = layer2(n1, n2, n3, n4, n5);
  var fapar = denormalize(l2, 0.000153013463222, 0.977135096979553);
  
  // Клиппинг к валидному диапазону [0, 1]
  fapar = Math.max(0, Math.min(1, fapar));
  
  return { default: [fapar] };
}

function neuron1(a,b,c,d,e,f,g,h,i,j,k){var s=-0.887068364040280+0.268714454733421*a-0.205473108029835*b+0.281765694196018*c+1.337443412255980*d+0.390319212938497*e-3.612714342203350*f+0.222530960987244*g+0.821790549667255*h-0.093664567310731*i+0.019290146147447*j+0.037364446377188*k;return tansig(s);}
function neuron2(a,b,c,d,e,f,g,h,i,j,k){var s=+0.320126471197199-0.248998054599707*a-0.571461305473124*b-0.369957603466673*c+0.246031694650909*d+0.332536215252841*e+0.438269896208887*f+0.819000551890450*g-0.934931499059310*h+0.082716247651866*i-0.286978634108328*j-0.035890968351662*k;return tansig(s);}
function neuron3(a,b,c,d,e,f,g,h,i,j,k){var s=+0.610523702500117-0.164063575315880*a-0.126303285737763*b-0.253670784366822*c-0.321162835049381*d+0.067082287973580*e+2.029832288655260*f-0.023141228827722*g-0.553176625657559*h+0.059285451897783*i-0.034334454541432*j-0.031776704097009*k;return tansig(s);}
function neuron4(a,b,c,d,e,f,g,h,i,j,k){var s=-0.379156190833946+0.130240753003835*a+0.236781035723321*b+0.131811664093253*c-0.250181799267664*d-0.011364149953286*e-1.857573214633520*f-0.146860751013916*g+0.528008831372352*h-0.046230769098303*i-0.034509608392235*j+0.031884395036004*k;return tansig(s);}
function neuron5(a,b,c,d,e,f,g,h,i,j,k){var s=+1.353023396690570-0.029929946166941*a+0.795804414040809*b+0.348025317624568*c+0.943567007518504*d-0.276341670431501*e-2.946594180142590*f+0.289483073507500*g+1.044006950440180*h-0.000413031960419*i+0.403331114840215*j+0.068427130526696*k;return tansig(s);}
function layer2(n1,n2,n3,n4,n5){return -0.336431283973339+2.126038811064490*n1-0.632044932794919*n2+5.598995787206250*n3+1.770444140578970*n4-0.267879583604849*n5;}
function normalize(u,min,max){return 2*(u-min)/(max-min)-1;}
function denormalize(n,min,max){return 0.5*(n+1)*(max-min)+min;}
function tansig(x){return 2/(1+Math.exp(-2*x))-1;}
"""
    return _wrap_with_cloudmask(core_setup, core_eval, use_cloud_mask=True, mosaicking="SIMPLE")


def _evalscript_lai() -> str:
    """
    Evalscript для LAI (Leaf Area Index).
    Основан на SNAP NN алгоритме из Sentinel Hub Custom Scripts.
    
    Returns:
        str: Evalscript V3 код с облачной маской
    """
    core_setup = """
{
  input: [{
    bands: ["B03","B04","B05","B06","B07","B8A","B11","B12",
            "viewZenithMean","viewAzimuthMean","sunZenithAngles","sunAzimuthAngles"]
  }],
  output: [{id:"default", bands:1, sampleType:"AUTO"}]
}
"""
    core_eval = r"""
var degToRad = Math.PI / 180;

function evaluatePixelOrig(samples) {
  var sample = samples[0];
  
  // Нормализация входных данных
  var b03_norm = normalize(sample.B03, 0, 0.255607);
  var b04_norm = normalize(sample.B04, 0, 0.291938);
  var b05_norm = normalize(sample.B05, 0, 0.307567);
  var b06_norm = normalize(sample.B06, 0.007004, 0.613413);
  var b07_norm = normalize(sample.B07, 0.014526, 0.760554);
  var b8a_norm = normalize(sample.B8A, 0.027440, 0.793957);
  var b11_norm = normalize(sample.B11, 0.016904, 0.497987);
  var b12_norm = normalize(sample.B12, 0, 0.494352);
  
  var viewZen_norm = normalize(Math.cos(sample.viewZenithMean * degToRad), 0.918595400582046, 1);
  var sunZen_norm  = normalize(Math.cos(sample.sunZenithAngles * degToRad), 0.342022871159208, 0.936206429175402);
  var relAzim_norm = Math.cos((sample.sunAzimuthAngles - sample.viewAzimuthMean) * degToRad);
  
  // Нейронная сеть
  var n1 = neuron1(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n2 = neuron2(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n3 = neuron3(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n4 = neuron4(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n5 = neuron5(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  
  var l2 = layer2(n1, n2, n3, n4, n5);
  var lai = denormalize(l2, 0.002, 6.0);
  
  // Клиппинг к валидному диапазону [0, 8]
  lai = Math.max(0, Math.min(8, lai));
  
  return { default: [lai] };
}

function neuron1(a,b,c,d,e,f,g,h,i,j,k){var s=+0.784808-0.137023*a+0.046769*b-0.507095*c+0.059367*d+0.479746*e-1.357460*f+0.083341*g+0.253529*h+0.037930*i-0.268747*j+0.301715*k;return tansig(s);}
function neuron2(a,b,c,d,e,f,g,h,i,j,k){var s=-0.372636-0.207983*a-0.100905*b+0.018108*c-0.280948*d+0.308629*e+0.782934*f-0.109214*g-0.652244*h-0.126916*i-0.283522*j-0.057708*k;return tansig(s);}
function neuron3(a,b,c,d,e,f,g,h,i,j,k){var s=-0.395026-0.133541*a-0.122994*b+0.010796*c-0.419717*d+0.356877*e+1.998431*f-0.207434*g-0.518681*h+0.072074*i-0.156707*j-0.008894*k;return tansig(s);}
function neuron4(a,b,c,d,e,f,g,h,i,j,k){var s=+0.128022+0.212186*a-0.052945*b-0.024536*c-0.041589*d-0.020826*e-1.796692*f-0.181030*g+0.625598*h-0.074544*i-0.013845*j-0.020874*k;return tansig(s);}
function neuron5(a,b,c,d,e,f,g,h,i,j,k){var s=-0.208894+0.179996*a+0.262594*b+0.122393*c+0.135604*d-0.147989*e-0.912822*f+0.058144*g+0.188219*h+0.174050*i-0.292004*j+0.009611*k;return tansig(s);}
function layer2(n1,n2,n3,n4,n5){return +1.096963107077220-1.500135489728730*n1-0.096283269121503*n2-0.194935930577094*n3-0.352305895755591*n4+0.075107415847473*n5;}
function normalize(u,min,max){return 2*(u-min)/(max-min)-1;}
function denormalize(n,min,max){return 0.5*(n+1)*(max-min)+min;}
function tansig(x){return 2/(1+Math.exp(-2*x))-1;}
"""
    return _wrap_with_cloudmask(core_setup, core_eval, use_cloud_mask=True, mosaicking="SIMPLE")


def _evalscript_fcover() -> str:
    """
    Evalscript для FCOVER (Fraction of Vegetation Cover).
    Основан на SNAP NN алгоритме из Sentinel Hub Custom Scripts.
    
    Returns:
        str: Evalscript V3 код с облачной маской
    """
    core_setup = """
{
  input: [{
    bands: ["B03","B04","B05","B06","B07","B8A","B11","B12",
            "viewZenithMean","viewAzimuthMean","sunZenithAngles","sunAzimuthAngles"]
  }],
  output: [{id:"default", bands:1, sampleType:"AUTO"}]
}
"""
    core_eval = r"""
var degToRad = Math.PI / 180;

function evaluatePixelOrig(samples) {
  var sample = samples[0];
  
  // Нормализация входных данных
  var b03_norm = normalize(sample.B03, 0, 0.253061520472);
  var b04_norm = normalize(sample.B04, 0, 0.290393577911);
  var b05_norm = normalize(sample.B05, 0, 0.305398915249);
  var b06_norm = normalize(sample.B06, 0.00663797254225, 0.608900395798);
  var b07_norm = normalize(sample.B07, 0.0139727270189, 0.753827384323);
  var b8a_norm = normalize(sample.B8A, 0.0266901380821, 0.782011770669);
  var b11_norm = normalize(sample.B11, 0.0163880741923, 0.493761397883);
  var b12_norm = normalize(sample.B12, 0, 0.49302598446);
  
  var viewZen_norm = normalize(Math.cos(sample.viewZenithMean * degToRad), 0.918595400582, 0.999999999991);
  var sunZen_norm  = normalize(Math.cos(sample.sunZenithAngles * degToRad), 0.342022871159, 0.936206429175);
  var relAzim_norm = Math.cos((sample.sunAzimuthAngles - sample.viewAzimuthMean) * degToRad);
  
  // Нейронная сеть
  var n1 = neuron1(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n2 = neuron2(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n3 = neuron3(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n4 = neuron4(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  var n5 = neuron5(b03_norm,b04_norm,b05_norm,b06_norm,b07_norm,b8a_norm,b11_norm,b12_norm,
                   viewZen_norm,sunZen_norm,relAzim_norm);
  
  var l2 = layer2(n1, n2, n3, n4, n5);
  var fcover = denormalize(l2, 0.0, 1.0);
  
  // Клиппинг к валидному диапазону [0, 1]
  fcover = Math.max(0, Math.min(1, fcover));
  
  return { default: [fcover] };
}

function neuron1(a,b,c,d,e,f,g,h,i,j,k){var s=+0.0137252282366+0.0620475742195*a-0.210637958422*b+0.00910504629206*c+1.30972609475*d+0.62612181421*e-2.55574799014*f+0.157617890355*g+0.0367979958686*h+0.09346914378*i-0.479103746331*j+0.344160187043*k;return tansig(s);}
function neuron2(a,b,c,d,e,f,g,h,i,j,k){var s=-0.633893997132+0.177727232172*a-0.0890540117122*b-0.306518961301*c+0.134721838239*d+0.0831366551838*e+0.448401871028*f+0.393642915*g-0.679321241292*h+0.478879910242*i-0.265800913171*j-0.188123881816*k;return tansig(s);}
function neuron3(a,b,c,d,e,f,g,h,i,j,k){var s=+1.02168965849-0.409688743281*a+1.08858884766*b+0.36284522554*c+0.0369390509705*d-0.348012590003*e-2.0035261881*f+0.0410357601757*g+1.22373853174*h-0.0124082778287*i-0.282223364524*j+1.028e-4*k;return tansig(s);}
function neuron4(a,b,c,d,e,f,g,h,i,j,k){var s=-0.498002810205-0.188970957866*a-0.0358621840833*b+0.00551248528107*c+1.35391570802*d-0.739689896116*e-2.21719530107*f+0.313216124198*g+1.5020168915*h+1.21530490195*i-0.421938358618*j+1.48852484547*k;return tansig(s);}
function neuron5(a,b,c,d,e,f,g,h,i,j,k){var s=-3.88922154789+2.49293993709*a-4.40511331388*b-1.91062012624*c-0.703174115575*d-0.215104721138*e-0.972151494818*f-0.930752241278*g+1.2143441876*h-0.521665460192*i-0.445755955598*j+0.344111873777*k;return tansig(s);}
function layer2(n1,n2,n3,n4,n5){return -0.0967998147811+0.23080586765*n1-0.333655484884*n2-0.499418292325*n3+0.0472484396749*n4-0.0798516540739*n5;}
function normalize(u,min,max){return 2*(u-min)/(max-min)-1;}
function denormalize(n,min,max){return 0.5*(n+1)*(max-min)+min;}
function tansig(x){return 2/(1+Math.exp(-2*x))-1;}
"""
    return _wrap_with_cloudmask(core_setup, core_eval, use_cloud_mask=True, mosaicking="SIMPLE")


def get_biopar_evalscript(biopar_type: str) -> str:
    """
    Возвращает evalscript для указанного типа биопараметра.
    
    Args:
        biopar_type: Тип параметра ('FAPAR', 'LAI', 'FCOVER', 'CCC', 'CWC')
        
    Returns:
        str: Evalscript V3 код
        
    Raises:
        NotImplementedError: Для CCC и CWC (используйте openEO)
        ValueError: Для неизвестных типов
    """
    bt = biopar_type.upper()
    
    if bt == "FAPAR":
        return _evalscript_fapar()
    if bt == "LAI":
        return _evalscript_lai()
    if bt == "FCOVER":
        return _evalscript_fcover()
    if bt in ("CCC", "CWC"):
        raise NotImplementedError(
            f"{bt} не поддержан через Sentinel Hub evalscript. "
            f"Используйте backend/biopar.py (openEO UDP)."
        )
    
    raise ValueError(
        f"biopar_type must be one of: FAPAR, LAI, FCOVER, CCC, CWC. Got: {biopar_type}"
    )


# ---------------------- Кэширование ---------------------- #

def _cache_key(
    bbox: List[float],
    start_date: str,
    end_date: str,
    width: int,
    height: int,
    max_cloud_coverage: int,
    mosaicking_order: Optional[str],
    biopar_type: str
) -> str:
    """
    Генерирует стабильный ключ кэша из параметров запроса.
    
    Args:
        bbox: Bounding box [minlon, minlat, maxlon, maxlat]
        start_date: Начальная дата (YYYY-MM-DD)
        end_date: Конечная дата (YYYY-MM-DD)
        width: Ширина выходного изображения
        height: Высота выходного изображения
        max_cloud_coverage: Максимальная облачность (%)
        mosaicking_order: Порядок мозаики
        biopar_type: Тип биопараметра
        
    Returns:
        str: Имя файла кэша
    """
    payload = {
        "bbox": [round(b, 6) for b in bbox],
        "start": start_date,
        "end": end_date,
        "w": int(width),
        "h": int(height),
        "cloud": int(max_cloud_coverage),
        "mosaic": mosaicking_order or "default",
        "biopar": biopar_type.upper(),
        "evalscript_version": EVALSCRIPT_VERSION
    }
    
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]  # First 16 chars for shorter filenames

    return f"biopar_{biopar_type.lower()}_{digest}.tif"


# ---------------------- Основная функция загрузки ---------------------- #

def fetch_biopar_geotiff(
    bbox: List[float],
    start_date: str,
    end_date: str,
    biopar_type: str = "FAPAR",
    width: int = 2048,
    height: int = 2048,
    max_cloud_coverage: int = 30,
    mosaicking_order: Optional[MosaickingOrder] = MosaickingOrder.LEAST_CC,
    harmonize_values: bool = True,
    max_retries: int = 2,
    retry_delay: int = 5,
    resampling: str = "BILINEAR",
    upsampling: Optional[str] = None,
    downsampling: Optional[str] = None
) -> Path:
    """
    Запрашивает BIOPAR (FAPAR/LAI/FCOVER) GeoTIFF через Sentinel Hub Processing API.

    Args:
        bbox: [minlon, minlat, maxlon, maxlat] в EPSG:4326
        start_date: Начальная дата в формате YYYY-MM-DD
        end_date: Конечная дата в формате YYYY-MM-DD
        biopar_type: Тип биопараметра ('FAPAR'|'LAI'|'FCOVER')
        width: Ширина выходного изображения в пикселях
        height: Высота выходного изображения в пикселях
        max_cloud_coverage: Максимальная облачность (0-100%)
        mosaicking_order: Порядок мозаики (mostRecent, leastRecent, leastCC)
        harmonize_values: Применять harmonization для Sentinel-2 L2A
        max_retries: Количество повторных попыток при временных ошибках
        retry_delay: Задержка между попытками в секундах
        resampling: Метод ресемплинга (NEAREST, BILINEAR, CUBIC, etc.)
        upsampling: Метод для upsampling (опционально)
        downsampling: Метод для downsampling (опционально)

    Returns:
        Path: Путь к кэшированному GeoTIFF файлу

    Raises:
        NoDataAvailableError: Нет спутниковых данных для периода/области
        AuthenticationError: Ошибка аутентификации
        SentinelHubError: Другие ошибки API
        NotImplementedError: Для CCC и CWC (используйте openEO)
        ValueError: Неверные входные параметры

    Examples:
        >>> path = fetch_biopar_geotiff(
        ...     bbox=[69.0, 51.0, 73.0, 53.0],
        ...     start_date="2024-06-01",
        ...     end_date="2024-06-30",
        ...     biopar_type="FAPAR",
        ...     max_cloud_coverage=30
        ... )
    """
    
    # Валидация входных параметров
    if len(bbox) != 4:
        raise ValueError("bbox must contain 4 values: [minlon, minlat, maxlon, maxlat]")
    
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("Invalid bbox: min values must be less than max values")
    
    if not (0 <= max_cloud_coverage <= 100):
        raise ValueError("max_cloud_coverage must be between 0 and 100")
    
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    
    # Проверка на CCC/CWC
    if biopar_type.upper() in ("CCC", "CWC"):
        raise NotImplementedError(
            f"{biopar_type.upper()} через Sentinel Hub не поддержан evalscript-ом. "
            f"Используйте openEO модуль backend/biopar.py."
        )
    
    # Конвертация MosaickingOrder enum в строку
    mosaic_str = mosaicking_order.value if isinstance(mosaicking_order, MosaickingOrder) else mosaicking_order
    
    # Проверка кэша
    cache_name = _cache_key(
        bbox, start_date, end_date, width, height,
        max_cloud_coverage, mosaic_str, biopar_type
    )
    cache_path = CACHE_DIR / cache_name
    
    if cache_path.exists():
        logger.info(f"Cache hit: {cache_name}")
        return cache_path
    
    logger.info(
        f"Fetching BIOPAR={biopar_type.upper()}: bbox={bbox}, "
        f"period={start_date}..{end_date}, size={width}x{height}, "
        f"cloud<={max_cloud_coverage}%, mosaic={mosaic_str}, "
        f"harmonize={harmonize_values}"
    )
    
    # Получение токена
    try:
        token = get_cdse_token()
    except AuthenticationError:
        raise
    
    # Генерация evalscript
    evalscript = get_biopar_evalscript(biopar_type)
    
    # Формирование dataFilter
    data_filter: Dict[str, Any] = {
        "timeRange": {
            "from": f"{start_date}T00:00:00Z",
            "to": f"{end_date}T23:59:59Z"
        },
        "maxCloudCoverage": max_cloud_coverage
    }
    
    if mosaic_str:
        data_filter["mosaickingOrder"] = mosaic_str
    
    # Формирование processing параметров
    processing: Dict[str, Any] = {}
    
    if harmonize_values:
        processing["harmonizeValues"] = True
    
    # Resampling параметры
    if upsampling:
        processing["upsampling"] = upsampling
    if downsampling:
        processing["downsampling"] = downsampling
    if resampling and not (upsampling or downsampling):
        processing["resampling"] = resampling
    
    # Формирование payload
    payload = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                }
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": data_filter
            }]
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{
                "identifier": "default",
                "format": {
                    "type": "image/tiff"
                }
            }]
        },
        "evalscript": evalscript
    }
    
    # Добавляем processing только если есть параметры
    if processing:
        payload["processing"] = processing
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Retry логика
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            logger.info(
                f"Sending request to Sentinel Hub Processing API "
                f"(attempt {attempt + 1}/{max_retries + 1})..."
            )
            
            resp = requests.post(
                SH_PROCESS_URL,
                headers=headers,
                json=payload,
                timeout=240
            )
            
            logger.info(f"Processing API response status: {resp.status_code}")
            
            # Обработка специфичных статусов
            if resp.status_code == 400:
                error_text = resp.text
                logger.error(f"Bad Request (400): {error_text}")
                
                # Проверяем индикаторы отсутствия данных
                error_lower = error_text.lower()
                if any(phrase in error_lower for phrase in [
                    "no data", "no satellite", "no scenes", "no products"
                ]):
                    raise NoDataAvailableError(
                        f"No satellite data available for {biopar_type.upper()} in period "
                        f"{start_date} to {end_date} with cloud coverage <= {max_cloud_coverage}%. "
                        f"Try expanding the date range or increasing max_cloud_coverage."
                    )
                
                raise SentinelHubError(f"Invalid request parameters: {error_text}")
            
            elif resp.status_code == 401:
                # Обновляем токен один раз
                if attempt < max_retries:
                    logger.warning("Authentication failed, refreshing token...")
                    token = get_cdse_token()
                    headers["Authorization"] = f"Bearer {token}"
                    time.sleep(retry_delay)
                    continue
                else:
                    raise AuthenticationError("Invalid or expired token")
            
            elif resp.status_code == 429:
                # Rate limit exceeded
                if attempt < max_retries:
                    retry_after = int(resp.headers.get("Retry-After", retry_delay * 1000)) / 1000
                    logger.warning(f"Rate limit exceeded, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    # Обновляем токен на случай его истечения
                    token = get_cdse_token()
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                else:
                    raise SentinelHubError(f"Rate limit exceeded after {max_retries} retries")
            
            elif resp.status_code in (502, 503, 504):
                # Временные ошибки сервера
                if attempt < max_retries:
                    logger.warning(
                        f"Server error {resp.status_code}, retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    raise SentinelHubError(
                        f"Sentinel Hub service unavailable (HTTP {resp.status_code}) "
                        f"after {max_retries} retries. Please try again later."
                    )
            
            elif resp.status_code != 200:
                logger.error(f"Processing API error ({resp.status_code}): {resp.text}")
                resp.raise_for_status()
            
            # Успешный ответ - проверяем содержимое
            content = resp.content
            content_length = len(content)
            
            # GeoTIFF должен иметь минимальный размер
            MIN_VALID_SIZE = 1000
            
            if content_length < MIN_VALID_SIZE:
                logger.warning(
                    f"Suspiciously small response: {content_length} bytes "
                    f"(expected > {MIN_VALID_SIZE})"
                )
                
                if attempt < max_retries:
                    logger.warning("Retrying due to small response...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise NoDataAvailableError(
                        f"Received empty or corrupted data for {start_date}..{end_date}. "
                        f"This usually means no valid satellite data is available for {biopar_type.upper()}."
                    )
            
            # Проверяем, что это действительно TIFF
            if not content.startswith(b'II\x2a\x00') and \
               not content.startswith(b'MM\x00\x2a'):
                logger.warning("Response doesn't appear to be a valid TIFF file")
                
                if attempt < max_retries:
                    logger.warning("Retrying due to invalid TIFF format...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise SentinelHubError(
                        "Received invalid TIFF data from API. "
                        "This may indicate a server-side processing error."
                    )
            
            # Сохраняем успешный результат атомарно
            # Используем atomic_write_cache для предотвращения частичных записей
            try:
                from backend.utils import atomic_write_cache
                atomic_write_cache(cache_path, content, use_lock=True)
                logger.info(
                    f"BIOPAR {biopar_type.upper()} saved: {cache_name}, "
                    f"size: {content_length:,} bytes"
                )
            except Exception as write_error:
                # Очистка при ошибке записи
                logger.error(f"Failed to write cache file: {write_error}")
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                        logger.debug(f"Cleaned up partial cache file: {cache_path}")
                    except Exception as cleanup_error:
                        logger.warning(f"Could not clean up cache file: {cleanup_error}")
                raise SentinelHubError(f"Failed to save GeoTIFF: {write_error}")

            # Сохраняем метаданные запроса
            metadata_path = cache_path.with_suffix('.json')
            metadata = {
                "bbox": bbox,
                "start_date": start_date,
                "end_date": end_date,
                "width": width,
                "height": height,
                "max_cloud_coverage": max_cloud_coverage,
                "mosaicking_order": mosaic_str,
                "biopar_type": biopar_type.upper(),
                "harmonize_values": harmonize_values,
                "file_size_bytes": content_length,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "evalscript_version": EVALSCRIPT_VERSION
            }

            try:
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f, indent=2)
            except Exception as meta_error:
                # Метаданные не критичны, логируем и продолжаем
                logger.warning(f"Could not save metadata: {meta_error}")

            return cache_path
        
        except requests.exceptions.Timeout:
            last_error = "Request timeout (240s)"
            if attempt < max_retries:
                logger.warning(f"Timeout, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                continue
            else:
                logger.error(f"Timeout after {max_retries} retries")
                raise SentinelHubError(
                    f"Request timeout after {max_retries} retries. "
                    f"The requested area or time range may be too large."
                )
        
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {e}"
            if attempt < max_retries:
                logger.warning(f"Connection error, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                continue
            else:
                logger.error(f"Connection error after {max_retries} retries")
                raise SentinelHubError(
                    f"Connection failed after {max_retries} retries: {e}"
                )
        
        except (NoDataAvailableError, AuthenticationError, SentinelHubError, NotImplementedError):
            # Эти ошибки не retry-им
            raise
        
        except Exception as e:
            last_error = str(e)
            logger.error(
                f"Unexpected error (attempt {attempt + 1}): {e}",
                exc_info=True
            )
            if attempt < max_retries:
                logger.warning(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                continue
            else:
                raise SentinelHubError(
                    f"Processing failed after {max_retries} retries: {last_error}"
                )
    
    # Не должны сюда попасть, но на всякий случай
    raise SentinelHubError(
        f"Failed to fetch BIOPAR after {max_retries} retries: {last_error}"
    )


# ---------------------- Управление кэшем ---------------------- #

def clear_cache(older_than_days: Optional[int] = None) -> int:
    """
    Очищает кэш BIOPAR файлов.
    
    Args:
        older_than_days: Удалить только файлы старше N дней (None = все)
        
    Returns:
        int: Количество удалённых файлов
    """
    if not CACHE_DIR.exists():
        return 0
    
    deleted = 0
    cutoff_time = None
    
    if older_than_days:
        cutoff_time = time.time() - (older_than_days * 86400)
    
    for file_path in CACHE_DIR.glob("*"):
        if file_path.is_file():
            try:
                if cutoff_time is None or file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
    
    logger.info(f"Cache cleanup: deleted {deleted} files")
    return deleted