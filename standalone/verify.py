#!/usr/bin/env python
# -*- coding: utf-8 -*-
#    Copyright © 2016 RunasSudo (Yingtong Li)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

# ily Python 3
from __future__ import print_function, unicode_literals

from mixnet.Ciphertext import Ciphertext
from mixnet.CiphertextCollection import CiphertextCollection
from mixnet.EGCryptoSystem import EGCryptoSystem
from mixnet.PrivateKey import PrivateKey
from mixnet.PublicKey import PublicKey
from mixnet.ShufflingProof import ShufflingProof

import hashlib, itertools, json, math, sys, urllib2

electionUrl = sys.argv[1].rstrip("/")

class VerificationException(Exception):
	pass

class statusCheck:
	def __init__(self, status):
		print(status, end="")
	def __enter__(self):
		return
	def __exit__(self, type, value, traceback):
		if value:
			print(": FAIL")
		else:
			print(": OK")

with statusCheck("Downloading election data"):
	# Election
	election = json.load(urllib2.urlopen(electionUrl))
	numQuestions = len(election['questions'])
	
	nbits = ((int(math.log(long(election["public_key"]["p"]), 2)) - 1) & ~255) + 256
	cryptosystem = EGCryptoSystem.load(nbits, long(election["public_key"]["p"]), int(election["public_key"]["g"])) # The generator might be a long if it's big? I don't know.
	pk = PublicKey(cryptosystem, long(election["public_key"]["y"]))
	
	# Ballots
	ballots = []
	ballotList = json.load(urllib2.urlopen(electionUrl + "/ballots"))
	for ballotInfo in ballotList:
		ballot = json.load(urllib2.urlopen(electionUrl + "/ballots/" + ballotInfo["voter_uuid"] + "/last"))
		ballots.append(ballot)
	
	# Results
	results = json.load(urllib2.urlopen(electionUrl + "/result"))
	
	# Mixes & Proofs
	mixnets = []
	numMixnets = json.load(urllib2.urlopen(electionUrl + "/mixnets"))
	for i in xrange(0, numMixnets):
		mixedAnswers = json.load(urllib2.urlopen(electionUrl + "/mixnets/" + str(i) + "/answers"))
		shufflingProof = json.load(urllib2.urlopen(electionUrl + "/mixnets/" + str(i) + "/proof"))
		mixnets.append((mixedAnswers, shufflingProof))
	
	# Trustees
	trustees = json.load(urllib2.urlopen(electionUrl + "/trustees"))

# Verify mixes
for i in xrange(0, numMixnets):
	index = numMixnets - i - 1
	for q in xrange(0, numQuestions):
		with statusCheck("Verifying mix " + str(index) + " question " + str(q)):
			proof = ShufflingProof.from_dict(mixnets[index][1][q], pk, nbits)
			
			orig = CiphertextCollection(pk)
			if i == 0:
				# Sometimes reverse=True and sometimes reverse=False???
				# TODO: Work out what's wrong
				for ballot in sorted(ballots, key=lambda k: k['voter_uuid'], reverse=True):
					ciphertext = Ciphertext(nbits, orig._pk_fingerprint)
					ciphertext.append(long(ballot["vote"]["answers"][q]["choices"][0]["alpha"]), long(ballot["vote"]["answers"][q]["choices"][0]["beta"]))
					orig.add_ciphertext(ciphertext)
			else:
				for ballot in mixnets[index + 1][0][q]["answers"]:
					ciphertext = Ciphertext(nbits, orig._pk_fingerprint)
					ciphertext.append(long(ballot["choice"]["alpha"]), long(ballot["choice"]["beta"]))
					orig.add_ciphertext(ciphertext)
			
			shuf = CiphertextCollection(pk)
			for ballot in mixnets[index][0][q]["answers"]:
				ciphertext = Ciphertext(nbits, shuf._pk_fingerprint)
				ciphertext.append(long(ballot["choice"]["alpha"]), long(ballot["choice"]["beta"]))
				shuf.add_ciphertext(ciphertext)
			
			# Check the challenge ourselves to provide a more informative error message
			expected_challenge = proof._generate_challenge(orig, shuf)
			if proof._challenge != expected_challenge:
				raise VerificationException("Challenge is wrong")
			
			# Do the maths
			if not proof.verify(orig, shuf):
				raise VerificationException("Shuffle failed to prove")

# Verify decryptions
for q in xrange(0, numQuestions):
	ballots = mixnets[0][0][q]["answers"]
	for i in xrange(0, len(ballots)):
		print("Verifying decryptions for question " + str(q) + " ballot " + str(i))
		ballot = ballots[i]
		result = long(results[q][i])
		decryption_factor_combination = 1L
		
		P = cryptosystem.get_prime()
		
		for j in xrange(0, len(trustees)):
			with statusCheck("Verifying decryption by trustee " + str(j)):
				factor = long(trustees[j]["decryption_factors"][q][i])
				proof = trustees[j]["decryption_proofs"][q][i]
				
				# Check the challenge
				C = long(proof["challenge"])
				expected_challenge = int(hashlib.sha1(proof["commitment"]["A"] + "," + proof["commitment"]["B"]).hexdigest(), 16)
				if C != expected_challenge:
					raise VerificationException("Challenge is wrong")
				
				# Do the maths
				T = long(proof["response"])
				
				GT = pow(cryptosystem.get_generator(), T, P)
				AYC = (long(proof["commitment"]["A"]) * pow(long(trustees[j]["public_key"]["y"]), C, P)) % P
				if GT != AYC:
					raise VerificationException("g^t != Ay^c (mod p)")
				
				AT = pow(long(ballot["choice"]["alpha"]), T, P)
				BFC = (long(proof["commitment"]["B"]) * pow(factor, C, P)) % P
				
				if AT != BFC:
					raise VerificationException("alpha^t != B(factor)^c (mod p)")
				
				decryption_factor_combination *= factor
		
		# Check the claimed decryption
		decryption_factor_combination *= (result + 1) # That +1 gets me every time...
		
		if (decryption_factor_combination % P) != (long(ballot["choice"]["beta"]) % P):
			print("FAIL")
			raise VerificationException("Claimed plaintext doesn't match decryption factors")

print("The election has passed validation. The results are:")
print(results)
