import xml.etree.ElementTree as ET
import sys
import os

if not os.path.exists("sim_build/results.xml"):
    print("TEST FAILED: results.xml not found")
    sys.exit(1)

try:
    tree = ET.parse("sim_build/results.xml")
    root = tree.getroot()
    fails = int(root.attrib.get("failures", 0))
    errs = int(root.attrib.get("errors", 0))
    
    # Also check all testsuites just in case
    for suite in root.findall(".//testsuite"):
        fails += int(suite.attrib.get("failures", 0))
        errs += int(suite.attrib.get("errors", 0))
        
    if fails > 0 or errs > 0:
        print(f"TEST FAILED: {fails} failures, {errs} errors")
        sys.exit(1)
except Exception as e:
    print(f"TEST FAILED: Error parsing results.xml: {e}")
    sys.exit(1)
