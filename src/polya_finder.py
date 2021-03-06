############################################################################
# Copyright (c) 2020 Saint Petersburg State University
# # All Rights Reserved
# See file LICENSE for details.
############################################################################

import logging
from functools import partial

import pybedtools as pbt
from Bio import Seq

logger = logging.getLogger('IsoQuant')


class PolyAFinder:
    def __init__(self, window_size=20, min_polya_fraction=0.8):
        self.window_size = window_size
        self.min_polya_fraction = min_polya_fraction
        self.polyA_count = int(self.window_size * self.min_polya_fraction)

    # == polyA stuff ==
    def find_polya_tail(self, alignment):
        logger.debug("Detecting polyA tail for %s " % alignment.query_name)
        cigar_tuples = alignment.cigartuples
        clipped_size = 0
        # hard clipped

        if len(cigar_tuples) > 1 and cigar_tuples[-1][0] == 5 and cigar_tuples[-2][0] == 4:
            clipped_size = cigar_tuples[-2][1]
        elif cigar_tuples[-1][0] == 4:
            clipped_size = cigar_tuples[-1][1]

        seq = alignment.seq
        if not seq:
            return -1
        # TODO check read end, but also check that we do not clip the entire last exon
        whole_tail_len = min(clipped_size, len(seq))
        check_tail_start = len(seq) - whole_tail_len
        check_tail_end = min(check_tail_start + 2 * self.window_size, len(seq))
        pos = self.find_polya(alignment.seq[check_tail_start:check_tail_end].upper())
        # logger.debug("start: %d, end: %d, len: %d, pos: %d" % (check_tail_start, check_tail_end, whole_tail_len, pos))
        # logger.debug(alignment.seq[check_tail_start:check_tail_end].upper())
        if pos == -1:
            logger.debug("No polyA found")
            return -1
        # FIXME this does not include indels
        ref_tail_start = alignment.reference_end + clipped_size - whole_tail_len
        ref_polya_start = ref_tail_start + pos + 1
        logger.debug("PolyA found at position %d" % ref_polya_start)
        return min(ref_polya_start, alignment.reference_end)

    def find_polyt_head(self, alignment):
        logger.debug("Detecting polyT head for %s " % alignment.query_name)
        cigar_tuples = alignment.cigartuples
        clipped_size = 0
        # hard clipped
        if len(cigar_tuples) > 1 and cigar_tuples[0][0] == 5 and cigar_tuples[1][0] == 4:
            clipped_size = cigar_tuples[1][1]
        elif cigar_tuples[0][0] == 4:
            clipped_size = cigar_tuples[0][1]

        seq = alignment.seq
        if not seq:
            return -1
        whole_head_len = min(clipped_size, len(seq))
        check_head_end = 0 + whole_head_len
        check_head_start = max(check_head_end - 2 * self.window_size, 0)

        rc_head = str(Seq.Seq(alignment.seq[check_head_start:check_head_end]).reverse_complement()).upper()
        pos = self.find_polya(rc_head)
        if pos == -1:
            logger.debug("No polyT found")
            return -1
        # FIXME this does not include indels
        ref_head_end = alignment.reference_start - clipped_size + whole_head_len
        ref_polyt_end = max(alignment.reference_start, ref_head_end - pos)
        logger.debug("PolyA found at position %d" % ref_polyt_end)
        return max(ref_polyt_end, alignment.reference_start)

    # poly A tail detection
    def find_polya(self, seq):
        if len(seq) < self.window_size:
            return -1
        i = 0
        while i < len(seq) - self.window_size:
            if seq[i:i + self.window_size].count('A') >= self.polyA_count:
                break
            i += 1
        if i >= len(seq) - self.window_size:
            return -1
        return i


class CagePeakFinder:
    def __init__(self, cage_file, shift_size=50, window_size=5):
        self.cage_peaks = self._load_cage_peaks(cage_file)
        self.shift_size = shift_size
        self.window_size = window_size

    def _load_cage_peaks(self, cage_file):
        return pbt.BedTool(cage_file)

    def _get_search_region(self, alignment, extended=False):
        contig = alignment.reference_name
        search_size = self.shift_size if extended else self.window_size
        if alignment.is_reverse:
            strand = '-'
            start = max(alignment.query_alignment_end - self.window_size, 0)
            end = alignment.query_alignment_end + search_size
        else:
            strand = '.'
            start = max(alignment.query_alignment_start - search_size, 0)
            end = alignment.query_alignment_start + self.window_size
        return contig, start, end, strand

    def find_cage_peak(self, alignment):
        logger.debug("Searching for cage peak for %s " % alignment.query_name)

        contig, start, end, strand = self._get_search_region(alignment, extended=True)
        alignment_interval = pbt.Interval(chrom=contig, start=start, end=end, strand=strand)
        cage_intersections = self.cage_peaks.all_hits(alignment_interval)

        if len(cage_intersections) > 0:
            logger.debug('CAGE peaks found: {}'.format(cage_intersections))
        else:
            logger.debug('No CAGE peaks found')

        return cage_intersections
