import os
import mne
import sys
import csv
import datetime

"""
Dependencies:
    1) mne 1.5.1
    2) Python 3.10+
    3) EDFlib-Python-1.0.8+

Usage:
    python3 edf_merge.py <edf-file-path> <[optional] output-file-name> <[optional] start-time> <[optional] duration-time>

Requirements:
    1) The <edf-file-path> directory stores the EDF files to be merged in a folder with the same name.
    2) If "Merge-checking" is on, the <edf-file-path> directory contains a '<name>_EDFMeta.csv'.

Example - Valid File Structure:
    .
    └── data_store0
        └── presidio
            └── nihon_kohden
                └── PR05
                    ├── PR05_EDFMeta.csv
                    └── PR05
                        ├── PR05_2605.edf
                        ├── PR05_2606.edf
                        └── PR05_2607.edf
                
    python3 edf_merge.py data_store0/presidio/nihon_kohden/PR05 False
"""


def trim_and_decim(edf_path: str, freq: int) -> mne.io.Raw:
    """Takes an EDF file path and returns the EDF data as an mne.io.Raw object with:
        - Only scalp channels included.
        - Resamples input EDF's frequency to 'freq'.
    """

    data: mne.io.Raw = mne.io.read_raw_edf(edf_path)  # alt preload=True, data.get_data() # alt *._data
    # Splice away 'POL'
    rename_dict: dict[str:str] = {name: name[4:] for name in data.ch_names}
    data: mne.io.Raw = data.rename_channels(rename_dict)
    # Remove non scalp-eeg
    channels: list[str] = data.ch_names
    scalp_start: int = channels.index('Fp1-Ref')
    to_drop = channels[:scalp_start]
    scalp_raw = data.drop_channels(to_drop)
    # Decimate 2000 hz to 200hz
    scalp_raw = scalp_raw.resample(freq)  # internally uses scipy.signal.decimate
    print_edf(scalp_raw, 'Output')
    return scalp_raw


def concat(lst: list[mne.io.Raw]) -> mne.io.Raw:
    """Concatenates a list of mne.io.Raw objects and returns result."""

    return mne.concatenate_raws(lst)


def bipolar_reference(raw_edf: mne.io.Raw) -> mne.io.Raw:
    cathodes = ['Fp1-Ref', 'F7-Ref', 'T7-Ref', 'P7-Ref', 'Fp1-Ref', 'F3-Ref', 'C3-Ref', 'P3-Ref', 'Fz-Ref', 'Cz-Ref',
                'Fp2-Ref', 'F4-Ref', 'C4-Ref', 'P4-Ref', 'Fp2-Ref', 'F8-Ref', 'T8-Ref', 'P8-Ref']
    anodes = ['F7-Ref', 'T7-Ref', 'P7-Ref', 'O1-Ref', 'F3-Ref', 'C3-Ref', 'P3-Ref', 'O1-Ref', 'Cz-Ref', 'Pz-Ref',
              'F4-Ref', 'C4-Ref', 'P4-Ref', 'O2-Ref', 'F8-Ref', 'T8-Ref', 'P8-Ref', 'O2-Ref']
    names = ['Fp1_F7', 'F7_T7', 'T7_P7', 'P7_O1', 'Fp1_F3', 'F3_C3', 'C3_P3', 'P3_O1', 'Fz_Cz', 'Cz_Pz', 'Fp2_F4',
             'F4_C4', 'C4_P4', 'P4_O2', 'Fp2_F8', 'F8_T8', 'T8_P8', 'P8_O2']
    return mne.set_bipolar_reference(raw_edf, anodes, cathodes, names)


def average_reference(raw_edf: mne.io.Raw) -> mne.io.Raw:
    return raw_edf.set_eeg_reference()


def export(raw_edf: mne.io.Raw, target_name: str, overwrite_existing=True, bipolar=False, common_average=False,
           bipolar_common_average=False):
    """Export raw object as EDF file"""
    mne.export.export_raw(target_name + '.edf', raw_edf, overwrite_existing)
    if bipolar:
        mne.export.export_raw(target_name + '-bipolar.edf', bipolar_reference(raw_edf), overwrite_existing)
    if common_average:
        mne.export.export_raw(target_name + '-common-average.edf', average_reference(raw_edf), overwrite_existing)
    if bipolar_common_average:
        mne.export.export_raw(target_name + '-bipolar-common-average.edf', average_reference(bipolar_reference(raw_edf)), overwrite_existing)


def print_edf(raw_edf: mne.io.Raw, name: str):
    """Print basic information about an mne.io.raw object."""
    print(f'\n\n\n\nTesting {name} EDF:\n')
    print(raw_edf.info)
    print('Dim:', raw_edf.get_data().shape[0], 'channels', 'x', raw_edf.get_data().shape[1], 'time points\n\n\n')


def str_to_time(time_str: str, time_format='%Y-%m-%d %H:%M:%S.%f'):
    return datetime.datetime.strptime(time_str, time_format)


def get_first_date(csv_in: str):
    with open(csv_in) as csv_file:
        csv_reader: csv.reader = csv.reader(csv_file, delimiter=',')
        _, first_row = next(csv_reader), next(csv_reader)
        return str_to_time(first_row[3])


def parse_find(csv_in: str, start, end, margin=datetime.timedelta(seconds=15)):
    """Iterate through 'csv_in' and return a list of lists, where each sublist contains an interval of EDF file names such that each EDF is less than 'margin'
       away from the previous file in time. This implementation relies on the fact that csv_in is sorted in time-chronological order. All returned EDF files
       are also constrained to be in the time range between 'start' and 'end'."""

    time_format = '%Y-%m-%d %H:%M:%S.%f'
    files = [[]]
    with open(csv_in) as csv_file:
        csv_reader = csv.reader(csv_file, delimiter=',')
        next(csv_reader)  # remove header

        row_0: list[str] = next(csv_reader)
        prev_name, prev_time_end = row_0[1], str_to_time(row_0[4])
        # files.append([prev_name])

        for row in csv_reader:
            curr_name: str = row[1]
            curr_time_start: datetime.datetime = str_to_time(row[3])
            # Do not record files earlier than start.
            if curr_time_start < start:
                continue

            # If the time difference is large, add a new list subsection.
            if curr_time_start - prev_time_end > margin:
                files.append([])

            # Add to list subsection.
            files[-1].append(curr_name)

            # Done recording once end time has been exceeded.
            if curr_time_start > end:
                break
            prev_time_end: datetime.datetime = datetime.datetime.strptime(row[4], time_format)
    return files


if __name__ == "__main__":  # can get rid of
    # Process command-line args
    print(sys.argv)
    argc: int = len(sys.argv)
    assert argc in range(2, 4), "Incorrect script parameters. Use "
    patient_path: str = sys.argv[1]
    if argc == 3:
        name = sys.argv[2]
    else:
        name = 'output'
    src = os.getcwd()
    print(src)
    sep = os.sep

    # Navigate to EDF files
    for _ in range(1):  # for server: while os.getcwd() is not sep:
        os.chdir('..')
    os.chdir(patient_path)

    # Merge EDF files
    patient = os.path.basename(os.getcwd())
    csv_meta = f'{patient}_EDFMeta.csv'
    print(csv_meta)
    assert csv_meta in os.listdir(), f'Please provide a .csv file formatted as: {patient}_EDFMeta.csv'

    # Identify start and end based on .csv, PR03_EDFMeta.csv
    t0 = get_first_date(csv_meta)  # Set start date
    t0 = t0.replace(hour=21, minute=0, second=0, microsecond=0)  # Set start date and time
    duration = datetime.timedelta(hours=11)  # Set target duration
    tf = t0 + duration  # Set end time

    # Retrieve list of sub lists. Each sublist is a set of continuous, in-range file names.
    edf_files = parse_find(csv_meta, t0, tf)
    os.chdir(patient)
    all_files = os.listdir()
    print(len(edf_files))
    for i, continuous_interval in enumerate(edf_files):
        print(i, continuous_interval)
        if len(continuous_interval) <= 1:
            continue
        merged = concat([trim_and_decim(edf, 200) for edf in continuous_interval if edf in all_files])
        os.chdir(src)
        os.chdir(f'out-{patient}')
        export(merged, f'{name}-{i}')
        os.chdir(patient_path + patient)
        # data, time = raw_obj[:,:]
        assert f'{name}-{i}' in os.listdir(), f'Export failed.'
