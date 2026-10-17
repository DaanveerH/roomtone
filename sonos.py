import urllib.request, urllib.error, xml.etree.ElementTree as ET, socket, time, re
from xml.sax.saxutils import escape

def soap(ip, service, action, timeout=4, **args):
    urn=f'urn:schemas-upnp-org:service:{service}:1'
    path=f'MediaRenderer/{service}' if service in ('AVTransport','RenderingControl','GroupRenderingControl') else service
    body=f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><u:{action} xmlns:u="{urn}">'+''.join(f'<{k}>{escape(str(v))}</{k}>' for k,v in args.items())+f'</u:{action}></s:Body></s:Envelope>'
    req=urllib.request.Request(f'http://{ip}:1400/{path}/Control',data=body.encode(),headers={'Content-Type':'text/xml; charset="utf-8"','SOAPAction':f'"{urn}#{action}"'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r: root=ET.fromstring(r.read())
    except urllib.error.HTTPError as e:
        detail=ET.fromstring(e.read()); msg=next((x.text for x in detail.iter() if x.tag.endswith('errorDescription')),str(e.code))
        raise RuntimeError(f'{action}: {msg}') from None
    return {x.tag.split('}')[-1]:x.text or '' for x in root.iter() if len(x)==0}

def discover():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(.5)
    msg=b'M-SEARCH * HTTP/1.1\r\nHOST:239.255.255.250:1900\r\nMAN:"ssdp:discover"\r\nMX:1\r\nST:urn:schemas-upnp-org:device:ZonePlayer:1\r\n\r\n'
    s.sendto(msg,('239.255.255.250',1900));end=time.monotonic()+2.5;ips=set()
    while time.monotonic()<end:
        try:
            d,a=s.recvfrom(65535)
            if b'Sonos' in d or b'ZonePlayer' in d:ips.add(a[0])
        except socket.timeout:pass
    s.close();return sorted(ips)

def topology(ip):
    root=ET.fromstring(soap(ip,'ZoneGroupTopology','GetZoneGroupState',timeout=1.5)['ZoneGroupState'])
    devices=[]
    for group in root.iter('ZoneGroup'):
        for m in group.iter('ZoneGroupMember'):
            if m.get('Invisible')=='1':continue
            devices.append({'id':m.get('UUID'),'name':m.get('ZoneName'),'ip':urllib.parse.urlparse(m.get('Location')).hostname,'coordinator':group.get('Coordinator'),'satellites':len(list(m.iter('Satellite')))})
    return devices

def seconds(t):
    try:
        a=[int(x) for x in t.split(':')];return sum(v*60**i for i,v in enumerate(reversed(a)))
    except (ValueError,AttributeError):return 0

def timestamp(n):
    n=max(0,int(n));return f'{n//3600:02}:{n//60%60:02}:{n%60:02}'
