# HPE CHIF dependency

Checked on 30 September 2026. The repository does not redistribute HPE's shared library, wheel or firmware and does not download them during installation.

## Acquisition

HPE documents the ilorest PyPI project as an official installation source:
https://servermanagementportal.ext.hpe.com/docs/redfishclients/ilorest-userguide/installation

The previously verified library came from this exact wheel, not from installing a current iLOrest release:

- Release metadata: https://pypi.org/pypi/ilorest/7.4.0.0/json
- Wheel: `ilorest-7.4.0.0-py2.py3-none-any.whl`
- Wheel SHA256: `bbe31c050f7ac79a8cf2fb48163655da5a4e9a4fe2ab88a05430639372624a9d`
- Member: `ilorest/chiflibrary/ilorest_chif.so`
- Linux x86-64 library SHA256: `33620a23d3356a9e3d7140f1bce9b91df515cbbed86a05514aff6a49a58673d0`

The wheel also contains an ARM library. It must not be selected for the ML350 Gen9. The extractor selects the exact x86-64 member, checks ELF architecture and both hashes, refuses overwrites, and executes no package code. Keep your downloaded wheel and accompanying notices privately. Copying the library for local use requires whatever rights HPE grants you.

The runtime verifies the same library hash before loading it. A newer download or the mutable standalone HPE download link is not automatically compatible. Other versions require a new audit, not bypassing the hash check.

## Terms and redistribution

HPE's Python library README explicitly makes in-band DLL/SO acquisition subject to the Hewlett Packard Enterprise Software License Agreement:
https://github.com/HewlettPackard/python-ilorest-library/blob/master/README.rst

The linked HPE licensing landing page is:
https://www.hpe.com/us/en/software/licensing.html

The published HPE enterprise EULA states in section 6 that its license is non-transferable and for internal use, and prohibits distributing, reselling or sublicensing software to third parties unless Supporting Material specifically permits it:
https://downloads.hpe.com/pub/softlib2/software1/doc/p1796552785/v113125/eula-en.html

The ilorest PyPI metadata has an Apache license classifier and its Python sources carry open-source notices. That does not establish a CHIF binary redistribution exception to HPE's separate DLL/SO guidance. Inspection of the pinned wheel did not reveal a distinct CHIF redistribution grant. Therefore no CHIF binary is packaged here. Users acquire it directly and review the applicable agreement and Supporting Material themselves. The `--accept-hpe-terms` flag records the user's decision; it does not grant a license.

## Host requirements

CHIF is a Linux x86-64 native shared library, not a pure Python dependency. Its load-time libc/dependency requirements must be satisfied on your distribution. A failed library load stops manual control. Do not install HPE daemons, flash firmware or substitute a different CHIF build to bypass preflight. See [kernel requirements](installation.md#stock-hpilo-driver).
