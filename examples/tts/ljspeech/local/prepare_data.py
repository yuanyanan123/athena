#coding=utf-8
# Copyright (C) 2020 ATHENA AUTHORS; LanYu;
# All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
""" LJspeech dataset
This is a public domain speech dataset consisting of 13,100 short audio clips of a single speaker
reading passages from 7 non-fiction books. A transcription is provided for each clip.
Clips vary in length from 1 to 10 seconds and have a total length of approximately 24 hours.
detailed information can be seen on https://keithito.com/LJ-Speech-Dataset
"""

import os
import re
import sys
import inflect
import codecs
import pandas
from absl import logging
from sklearn.model_selection import train_test_split
from unidecode import unidecode

import tensorflow as tf
from athena import get_wave_file_length


GFILE = tf.compat.v1.gfile

#------------normalize_numbers--------------#
_INFLECT = inflect.engine()
_COMMA_NUMBER_RE = re.compile(r'([0-9][0-9\,]+[0-9])')
_DECIMAL_NUMBER_RE = re.compile(r'([0-9]+\.[0-9]+)')
_POUNDS_RE = re.compile(r'£([0-9\,]*[0-9]+)')
_DOLLARS_RE = re.compile(r'\$([0-9\.\,]*[0-9]+)')
_ORDINAL_RE = re.compile(r'[0-9]+(st|nd|rd|th)')
_NUMBER_RE = re.compile(r'[0-9]+')

def _remove_commas(m):
    return m.group(1).replace(',', '')

def _expand_decimal_point(m):
    return m.group(1).replace('.', ' point ')

def _expand_dollars(m):
    match = m.group(1)
    parts = match.split('.')
    if len(parts) > 2:
        return match + ' dollars'  # Unexpected format
    dollars = int(parts[0]) if parts[0] else 0
    cents = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    if dollars and cents:
        dollar_unit = 'dollar' if dollars == 1 else 'dollars'
        cent_unit = 'cent' if cents == 1 else 'cents'
        return '%s %s, %s %s' % (dollars, dollar_unit, cents, cent_unit)
    elif dollars:
        dollar_unit = 'dollar' if dollars == 1 else 'dollars'
        return '%s %s' % (dollars, dollar_unit)
    elif cents:
        cent_unit = 'cent' if cents == 1 else 'cents'
        return '%s %s' % (cents, cent_unit)
    else:
        return 'zero dollars'

def _expand_ordinal(m):
    return _INFLECT.number_to_words(m.group(0))

def _expand_number(m):
    num = int(m.group(0))
    if num > 1000 and num < 3000:
        if num == 2000:
            return 'two thousand'
        elif num > 2000 and num < 2010:
            return 'two thousand ' + _INFLECT.number_to_words(num % 100)
        elif num % 100 == 0:
            return _INFLECT.number_to_words(num // 100) + ' hundred'
        else:
            return _INFLECT.number_to_words(num, andword='', zero='oh', group=2).replace(', ', ' ')
    else:
        return _INFLECT.number_to_words(num, andword='')

def normalize_numbers(text):
    """
    normalize numbers in text
    """
    text = re.sub(_COMMA_NUMBER_RE, _remove_commas, text)
    text = re.sub(_POUNDS_RE, r'\1 pounds', text)
    text = re.sub(_DOLLARS_RE, _expand_dollars, text)
    text = re.sub(_DECIMAL_NUMBER_RE, _expand_decimal_point, text)
    text = re.sub(_ORDINAL_RE, _expand_ordinal, text)
    text = re.sub(_NUMBER_RE, _expand_number, text)
    return text

#---------------clean_text---------------#
# Regular expression matching whitespace:
_whitespace_re = re.compile(r'\s+')

# List of (regular expression, replacement) pairs for abbreviations:
_abbreviations = [(re.compile('\\b%s\\.' % x[0], re.IGNORECASE), x[1]) for x in [
    ('Mrs', 'Misess'),
    ('Mr', 'Mister'),
    ('Dr', 'Doctor'),
    ('St', 'Saint'),
    ('Co', 'Company'),
    ('Jr', 'Junior'),
    ('Maj', 'Major'),
    ('Gen', 'General'),
    ('Drs', 'Doctors'),
    ('Rev', 'Reverend'),
    ('Lt', 'Lieutenant'),
    ('Hon', 'Honorable'),
    ('Sgt', 'Sergeant'),
    ('Capt', 'Captain'),
    ('Esq', 'Esquire'),
    ('Ltd', 'Limited'),
    ('Col', 'Colonel'),
    ('Ft', 'Fort'),
]]

def expand_abbreviations(text):
    """
    expand abbreviations in text
    """
    for regex, replacement in _abbreviations:
        text = re.sub(regex, replacement, text)
    return text

def collapse_whitespace(text):
    """
    collapse whitespace in text
    """
    return re.sub(_whitespace_re, ' ', text)

def convert_to_ascii(text):
    return unidecode(text)

# NOTE (kan-bayashi): Following functions additionally defined, not inclueded in original codes.
def remove_unnecessary_symbols(text):
    """
    remove unnecessary symbols in text
    """
    text = re.sub(r'[\(\)\[\]\<\>\"]+', '', text)
    return text

def expand_symbols(text):
    """
    expand symbols in text
    """
    text = re.sub("\;", ",", text)
    text = re.sub("\:", ",", text)
    text = re.sub("\-", " ", text)
    text = re.sub("\&", "and", text)
    return text

def preprocess(text):
    '''Custom pipeline for English text, including number and abbreviation expansion.'''
    text = convert_to_ascii(text)
    text = normalize_numbers(text)
    text = expand_abbreviations(text)
    text = expand_symbols(text)
    text = remove_unnecessary_symbols(text)
    text = collapse_whitespace(text)
    return text

#----------------create total.csv-----------------
def convert_audio_and_split_transcript(dataset_dir, total_csv_path):
    """Convert rar to WAV and split the transcript.
      Args:
    dataset_dir  : the directory which holds the input dataset.
    total_csv_path : the resulting output csv file.

    LJSpeech-1.1 dir Tree structure:
    LJSpeech-1.1
        -metadata.csv
            -LJ001-0002|in being comparatively modern.|in being comparatively modern.
            ...
        -wavs
            -LJ001-0001.wav
            -LJ001-0002.wav
            ...
            -LJ050-0278
        -pcms
            -audio-LJ001-0001.s16
            -audio-LJ001-0002.s16
            ...
    """
    logging.info("ProcessingA audio and transcript for {}".format("all_files"))
    wav_dir = os.path.join(dataset_dir, "LJSpeech-1.1/wavs/")

    files = []
    # ProsodyLabel ---word
    with codecs.open(os.path.join(dataset_dir, "LJSpeech-1.1/metadata.csv"),
                     "r",
                     encoding="utf-8") as f:
        for line in f:
            wav_name = line.split('|')[0] + '.wav'
            wav_file = os.path.join(wav_dir, wav_name)
            wav_length = get_wave_file_length(wav_file)
            #get transcript
            content = line.split('|')[2]
            clean_content = preprocess(content.rstrip())
            transcript = ' '.join(list(clean_content))
            transcript = transcript.replace('  ', ' <space>')
            transcript = 'sp1 ' + transcript + ' sil' #' sil\n'
            files.append((os.path.abspath(wav_file), wav_length, transcript))

    # Write to txt file which contains three columns:
    fp = open(total_csv_path, 'w', encoding="utf-8")

    fp.write("wav_filename"+'\t'
             "wav_length_ms"+'\t'
             "transcript"+'\n')
    for i in range(len(files)):
        fp.write(str(files[i][0])+'\t')
        fp.write(str(files[i][1])+'\t')
        fp.write(str(files[i][2])+'\n')

    fp.close()
    
    logging.info("Successfully generated csv file {}".format(total_csv_path))


def split_train_dev_test(total_csv, output_dir):
    # get total_csv
    data = pandas.read_csv(total_csv, encoding='utf-8', sep='\t')
    x, y = data.iloc[:, :2], data.iloc[:, 2:]
    # split train/dev/test0
    x_train, x_rest, y_train, y_rest = train_test_split(x, y, test_size=0.1, random_state=0)
    x_test, x_dev, y_test, y_dev = train_test_split(x_rest, y_rest, test_size=0.9, random_state=0)
    # add ProsodyLabel
    x_train.insert(2, 'transcript', y_train)
    x_test.insert(2, 'transcript', y_test)
    x_dev.insert(2, 'transcript', y_dev)
    # get csv_path
    train_csv_path = os.path.join(output_dir, 'train.csv')
    dev_csv_path = os.path.join(output_dir, 'dev.csv')
    test_csv_path = os.path.join(output_dir, 'test.csv')
    # generate csv
    x_train.to_csv(train_csv_path, index=False, sep="\t")
    logging.info("Successfully generated csv file {}".format(train_csv_path))
    x_dev.to_csv(dev_csv_path, index=False, sep="\t")
    logging.info("Successfully generated csv file {}".format(dev_csv_path))
    x_test.to_csv(test_csv_path, index=False, sep="\t")
    logging.info("Successfully generated csv file {}".format(test_csv_path))


def processor(dircetory):
    """ download and process """
    # get total_csv
    logging.info("Processing the LJspeech total.csv in {}".format(dircetory))
    total_csv_path = os.path.join(dircetory, "total.csv")
    convert_audio_and_split_transcript(dircetory, total_csv_path)
    split_train_dev_test(total_csv_path, dircetory)
    logging.info("Finished processing LJspeech csv ")


if __name__ == "__main__":
    logging.set_verbosity(logging.INFO)
    DIR = sys.argv[1] 
    processor(DIR)
